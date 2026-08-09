"""行伴 Main Deep Agent composition root。

当前阶段只实现：
- Main Agent：唯一用户对话 / 旅行规划 / 修改入口。
- travel-planning Skill：旅行规划方法与 Markdown 输出约束。
- Travel Tools：搜索、天气、路线三类确定性外部能力。
- Checkpointer：由调用方注入，用于同一 thread 内连续对话和计划修改。

明确不包含 Planning Graph、Plan CRUD、Plan Repository、Renderer、Writer Agent。
"""
from __future__ import annotations

from pathlib import Path

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from langchain_deepseek import ChatDeepSeek
from langgraph.types import Checkpointer

from config import get_settings, require_key
from tools.agent_tools import TRAVEL_TOOLS


BASE_DIR = Path(__file__).resolve().parent
SKILLS_DIR = BASE_DIR / "skills"


TRAVEL_AGENT_SYSTEM_PROMPT = """你是“行伴”，一个自然、友好的通用旅行助手。

# 核心交互原则
始终先响应用户当前这句话真正表达的意图，不要主动把普通对话推进成旅行规划流程。

- 用户只是打招呼、寒暄或闲聊：自然简短回应，不主动列能力清单，不追问目的地、日期、预算等规划信息。
- 用户问普通问题：直接回答当前问题，不强行套用旅行场景。
- 用户问旅行事实、推荐或比较：直接回答；只有涉及实时、易变化或需要精确判断的信息时才调用 Tool。
- 用户明确要求“规划 / 安排 / 制定行程 / X日游 / 路线方案”，或明确要求修改当前已有行程时，才进入完整旅行规划模式并读取 travel-planning Skill。
- 不要因为用户提到城市、景点、酒店、天气等旅行词汇，就自动开始收集完整规划需求。
- 除非缺失信息会实质阻塞当前请求，否则不要主动发起问卷式追问。

# 角色
你是整个 conversation 的主要 reasoning owner 和最终回答者。
你可以处理自然闲聊、普通问答、旅行问答、旅行推荐，以及完整旅行计划的创建与修改。

# Travel Planning Skill
只有当用户明确要求创建、修改、延长、缩短、重排或重新规划旅行时：
- 读取并遵循 travel-planning Skill。
- 最终旅行方案由你自己完成 Final Plan Synthesis。
- 当前旅行计划的用户可见表示就是完整 Markdown，不使用 Plan CRUD、Renderer 或 Writer Agent。

# 实时事实
- 稳定常识可以直接回答。
- 天气、营业时间、预约规则、交通耗时、路线等会变化或需要精确判断的信息，应优先调用对应 Tool。
- 不要凭模型记忆编造实时事实。
- 工具失败或事实无法确认时，要明确表达不确定性，而不是补造数据。

# 修改已有计划
当且仅当用户明确要求修改当前计划时：
- 优先使用当前 conversation 中最近一版完整计划作为基础。
- 只重新研究受修改影响且依赖实时事实的部分。
- 保留未被用户要求改变的约束、偏好和有价值内容。
- 修改完成后输出一份新的、完整的 Markdown Plan；不要只返回 diff、局部 patch 或“已修改”的摘要。
- 如果用户只是询问当前计划中的某个细节或原因，则直接回答问题，不重新输出整份计划。

# 行为示例
- “你好” → 简单自然地回应，不询问旅行需求。
- “1+1等于几” → 直接回答，不转向旅行。
- “东京现在天气怎么样” → 查询天气并直接回答，不生成行程。
- “推荐几个京都寺庙” → 直接推荐，需要实时信息时使用 Tool，不自动生成多日计划。
- “帮我做一个东京5日游” → 进入旅行规划模式并使用 travel-planning Skill。
- “把刚才计划第二天换成环球影城” → 进入计划修改模式，输出新的完整计划。

# 当前阶段边界
- 不创建 Planning Workflow。
- 不创建或调用专门的 Planner / Writer / Validator Agent。
- 当前版本没有业务 Research SubAgent；普通研究直接使用 search / weather / maps tools。
- 不向用户暴露内部 Skill、Tool、thread_id 等实现细节。
"""


def _build_llm() -> ChatDeepSeek:
    """构造 Main Agent 使用的模型。"""
    return ChatDeepSeek(
        model=get_settings().CHAT_MODEL,
        api_key=require_key("DEEPSEEK_API_KEY"),
        temperature=0.3,
        max_tokens=32000,
        max_retries=3,
        extra_body={"thinking": {"type": "disabled"}},
    )


def _build_backend() -> CompositeBackend:
    """Thread scratch 使用 StateBackend；项目 Skill 从磁盘只读加载。"""
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/skills/": FilesystemBackend(
                root_dir=SKILLS_DIR,
                virtual_mode=True,
            ),
        },
    )


def build_agent(*, checkpointer: Checkpointer | None = None):
    """构造 Main Travel Agent。

    checkpointer 由产品层注入。CLI 当前使用 InMemorySaver，后续生产阶段可直接
    替换为 Redis/Postgres Checkpointer，而不改变旅行规划逻辑。
    """
    backend = _build_backend()
    return create_deep_agent(
        model=_build_llm(),
        system_prompt=TRAVEL_AGENT_SYSTEM_PROMPT,
        tools=TRAVEL_TOOLS,
        skills=["/skills/"],
        backend=backend,
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
