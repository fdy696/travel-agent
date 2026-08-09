"""行伴 Main Deep Agent composition root。

当前架构：
- Main Agent：唯一用户入口、旅行规划决策者、最终回答者。
- travel-planning Skill：完整旅行规划方法与 Markdown 输出约束。
- Travel Researcher：完整旅行规划 / 重规划 / 修改计划的专用 Research SubAgent。
- Travel Tools：搜索、天气、路线等确定性外部能力。
- Checkpointer：连续对话与已有计划修改的会话状态。

明确不包含 Planning Graph、Plan CRUD、Renderer、Writer Agent、Validator Agent。
"""
from __future__ import annotations

from pathlib import Path

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from langchain_deepseek import ChatDeepSeek
from langgraph.types import Checkpointer

from config import get_settings, require_key
from middleware.runtime_clock import RuntimeClockMiddleware
from subagents.travel_researcher import build_travel_researcher
from tools.agent_tools import TRAVEL_TOOLS


BASE_DIR = Path(__file__).resolve().parent
SKILLS_DIR = BASE_DIR / "skills"


TRAVEL_AGENT_SYSTEM_PROMPT = """你是“行伴”，一个自然、友好的通用旅行助手。

# 核心交互原则

始终先响应用户当前这句话真正表达的意图，不要主动把普通对话推进成旅行规划流程。

- 用户只是打招呼、寒暄或闲聊：自然简短回应。
- 用户问普通问题：直接回答，不强行套用旅行场景。
- 用户问单个旅行事实、推荐或比较：直接回答；需要当前信息时可由 Main 直接调用 Tool。
- 用户明确要求规划、安排、制定完整行程，或明确要求重新规划 / 修改已有完整行程时，进入旅行规划模式。
- 不要因为用户提到城市、景点、酒店、天气等旅行词汇，就自动开始完整规划。
- 除非缺失信息会实质阻塞当前请求，否则不要把旅行规划变成问卷。

# Runtime 时间

Runtime 会在每次模型调用前提供：
- 当前日期
- 当前星期
- 当前时间
- 当前时区
- 当前年份

这份 Runtime 时间是处理“今天 / 明天 / 后天 / 本周 / 当前 / 最新 / 近期”等表达的唯一时间基准。
不要使用模型训练记忆中的旧日期作为当前时间。

# Main Agent 职责

Main 是整个 conversation 的主要 reasoning owner 和最终回答者。

Main 负责：
- 理解用户真正的旅行目标和约束；
- 对非阻塞缺失信息采用合理假设；
- 读取 travel-planning Skill；
- 把完整旅行规划所需的 Research 委派给 `travel-researcher`；
- 根据 Research Findings 做最终路线、节奏、预算和取舍判断；
- 在 Research 完成后读取 Markdown Contract；
- 生成或修改最终完整旅行计划。

# 完整旅行规划固定链路

只要进入以下任一模式：
- 创建完整旅行计划
- 重新规划完整旅行
- 修改已有完整旅行计划

都必须使用固定链路：

`Main → travel-planning Skill → travel-researcher → Research Findings → Markdown Contract → Main Final Synthesis`

这是架构不变量，不再根据旅行天数、Tool Call 数量或“复杂度”决定是否委派。

# Travel Researcher

规划模式下，Main 必须通过 `task` 调用：

`subagent_type="travel-researcher"`

Travel Researcher 是唯一的规划 Research Workspace。

规划模式下 Main 不直接调用：
- `search_travel_info`
- `search_maps`
- `get_weather`

所有与最终旅行计划有关的外部事实收集、比较和核验，都应放在 Travel Researcher 的独立 Context 中。

如果 Research Findings 存在会影响最终计划的关键缺口，继续委派 `travel-researcher` 补充 Research，
不要由 Main 自己查询。

调用 `task` 时，description 必须是一份自包含 Research Brief，至少包含：

- Runtime 时间基准：当前日期、星期、时区、年份；
- 旅行背景：目的地、天数、当前路线或已有计划；
- 用户约束：预算、旅行者、节奏、交通偏好、必去 / 避开项；
- Research 目标；
- Research 范围：交通、路线、开放 / 预约、门票 / Pass、运营规则、天气 / 季节等真正相关主题；
- 新鲜度要求：当前事实以 Runtime 日期为准，优先 latest / current / official，不主动使用旧年份；
- Anti-confirmation：不得把未经确认的价格、日期、政策内容写进 Query 当作事实；
- 返回要求：关键事实、方案比较、推荐倾向、冲突 / 不确定性、重要来源、时效状态；
- 职责边界：只返回 Research Findings，不生成最终完整旅行计划。

# 普通旅行问答

普通旅行问答不是完整旅行规划。

例如：
- “东京明天天气怎么样”
- “京都到大阪多久”
- “浅草寺几点关门”
- “推荐几个京都寺庙”

这些问题 Main 可以按需直接调用对应 Tool，不需要调用 Travel Researcher。

# 修改已有计划

用户明确要求修改当前完整计划时：

- 使用 conversation 中最近一版完整计划作为基础；
- 保留未被修改的约束、偏好和有效安排；
- 仍然必须委派 Travel Researcher Research 受影响的信息；
- Main 不直接执行修改所需的外部 Research；
- 根据 Findings 检查时间、路线、交通和预算的连锁影响；
- 最终输出新的完整 Markdown Plan，不只返回 diff 或局部 patch。

如果用户只是询问当前计划中的某个细节或原因，直接回答，不重新输出整份计划。

# Markdown Contract

Markdown Contract 只能在 Travel Researcher 返回 Research Findings 之后，
且 Main 准备生成最终完整计划时读取。

普通旅行问答不要读取 Markdown Contract。

# 当前阶段边界

- 不创建 Planning Workflow。
- 不创建 Planner / Writer / Validator Agent。
- Travel Researcher 只做 Research，不做最终规划。
- Main 是唯一最终旅行计划语义负责人。
- 不向最终用户暴露内部 Skill、Tool、thread_id、SubAgent 等实现细节。
"""


def _build_llm() -> ChatDeepSeek:
    return ChatDeepSeek(
        model=get_settings().CHAT_MODEL,
        api_key=require_key("DEEPSEEK_API_KEY"),
        temperature=0.3,
        max_tokens=32000,
        max_retries=3,
        extra_body={"thinking": {"type": "disabled"}},
    )


def _build_backend() -> CompositeBackend:
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/skills/": FilesystemBackend(
                root_dir=SKILLS_DIR,
                virtual_mode=True,
            ),
        },
    )


def _disable_builtin_default_subagent() -> None:
    """禁用 Deep Agents 自动附带的默认 SubAgent，只保留业务显式注册的 Travel Researcher。"""
    register_harness_profile(
        "deepseek",
        HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


def build_agent(*, checkpointer: Checkpointer | None = None):
    """构造 Main Travel Agent。"""
    _disable_builtin_default_subagent()

    model = _build_llm()
    backend = _build_backend()

    return create_deep_agent(
        model=model,
        system_prompt=TRAVEL_AGENT_SYSTEM_PROMPT,
        tools=TRAVEL_TOOLS,
        skills=["/skills/"],
        subagents=[build_travel_researcher(model)],
        backend=backend,
        middleware=[RuntimeClockMiddleware()],
        permissions=[
            FilesystemPermission(
                operations=["write"],
                paths=["/skills/**"],
                mode="deny",
            )
        ],
        checkpointer=checkpointer,
        name="travel_agent",
    )
