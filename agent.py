"""Main Deep Agent：自然路由 + 一个 Travel Plan 专业 SubAgent。

架构：
- Main Agent：普通问答、实时工具调用、conversation-context 内的 Plan 追问。
- travel-planning declarative SubAgent：所有 Plan mutation（创建 + 修改），用于 context quarantine。
- Requirements / Current Plan：Repository canonical state。
- Skills：Travel Plan procedure，按需加载。
- 不使用自定义 Planning LangGraph Workflow。
"""
from __future__ import annotations

from pathlib import Path

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.memory import InMemorySaver

from config import get_settings, require_key
from planning.domain_tools import build_plan_domain_tools
from planning.plan_agent import build_travel_plan_subagent
from planning.repository import SQLitePlanningRepository
from planning.runtime import TravelRuntimeContext
from tools.agent_tools import TRAVEL_TOOLS


BASE_DIR = Path(__file__).resolve().parent
SKILLS_DIR = BASE_DIR / "skills"


TRAVEL_AGENT_SYSTEM_PROMPT = """你是“行伴”旅游助手，一位专业、贴心、务实的旅行伙伴。

# 普通问答
- 闲聊、稳定的旅游常识可以直接回答。
- 天气、交通、价格、营业时间、攻略等实时/可变信息必须调用对应工具后回答。
- 当前/近 3 天天气用 get_weather；更远日期的季节气候使用联网搜索。
- 路线、距离、耗时使用 search_maps。

# Conversation Context 优先
用户对刚生成/刚修改的行程做简单追问，例如“第二天住哪”“为什么这样安排”，
只要当前 conversation context 足够，直接回答，不要重新委派，也不要为了形式再查数据库。
只有上下文已经不足、被压缩，或者用户明确要求“当前最终保存版本”时，才调用 get_current_plan 读取 canonical state。

# Plan Mutation
当用户希望改变 Plan 时，通过 task 委派给 subagent_type="travel-planning"：
- 创建一个新的完整多日行程
- 上一轮规划缺信息，本轮继续补充
- 修改/删除/增加活动
- 延长/缩短天数
- 换目的地、预算、节奏、住宿方案
- 重新规划当前行程

Main Agent 不需要再做 create/modify 二次意图分类；只判断“这是不是 Plan mutation”。
委派时 description 使用用户本轮原话；只有本轮表述过短或存在歧义时，补一小段必要上下文。

travel-planning 返回缺信息问题时，自然转达给用户。
返回完整 Markdown 时必须原样完整转达，不再次总结、压缩或改写。

# 边界
- 普通天气/攻略/路线问题不要启动 travel-planning。
- 不暴露内部工具名、subagent 名、user_id、session_id、plan_id 等技术细节。
- 不编造实时事实。
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
    # default StateBackend 只保存 agent scratch files；/skills/ 映射到项目内只读 Skill。
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/skills/": FilesystemBackend(
                root_dir=SKILLS_DIR,
                virtual_mode=True,
            ),
        },
    )


def build_agent():
    llm = _build_llm()
    repository = SQLitePlanningRepository()
    domain_tools = build_plan_domain_tools(repository)
    planning_subagent = build_travel_plan_subagent(domain_tools=domain_tools)

    return create_deep_agent(
        model=llm,
        system_prompt=TRAVEL_AGENT_SYSTEM_PROMPT,
        tools=[*TRAVEL_TOOLS, domain_tools.get_current_plan],
        subagents=[planning_subagent],
        backend=_build_backend(),
        permissions=[
            FilesystemPermission(
                operations=["write"],
                paths=["/skills/**"],
                mode="deny",
            ),
        ],
        checkpointer=InMemorySaver(),
        context_schema=TravelRuntimeContext,
        name="travel_agent",
    )
