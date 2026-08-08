"""Main Deep Agent composition root.

最终架构：
- Main Agent：唯一核心业务 Agent，负责普通问答、闲聊、旅游规划和 Plan 修改。
- travel-planning Skill：按需加载旅游规划 procedure。
- travel-researcher：只读 Research SubAgent，仅用于高输出量研究的 context isolation。
- Domain Tools：Requirements / Current Plan 的确定性业务边界。
- Redis Checkpointer：conversation/thread persistence，由应用生命周期注入。
"""
from __future__ import annotations

from pathlib import Path

from typing import TypedDict, Literal

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.core.state import AgentState
from langchain_deepseek import ChatDeepSeek
from langgraph.types import Checkpointer

from config import get_settings, require_key
from middleware import PlanCompletionMiddleware
from planning.domain_tools import build_plan_domain_tools
from planning.repository import SQLitePlanningRepository
from planning.runtime import TravelRuntimeContext
from subagents.research import build_travel_researcher
from tools.agent_tools import TRAVEL_TOOLS


class TravelAgentState(AgentState):
    """Custom state for the travel agent, including planning status."""

    plan_task_status: Literal["none", "pending", "committed"]
    completion_retry: int


BASE_DIR = Path(__file__).resolve().parent
SKILLS_DIR = BASE_DIR / "skills"


TRAVEL_AGENT_SYSTEM_PROMPT = """你是“行伴”旅游助手，一位专业、贴心、务实的旅行伙伴。

# 核心职责
你负责两个核心能力：
1. 普通问答 / 闲聊。
2. 完整旅游规划，包括创建、修改、延长、缩短、重排和重新规划。

你是用户整个 conversation 的主要 reasoning owner，不要把旅游规划本身委派给其他业务 Agent。

# 普通问答
- 闲聊、稳定旅游常识可以直接回答。
- 天气、交通、价格、营业时间、攻略等实时/可变信息必须调用对应工具后回答。
- 当前/近 3 天天气使用 get_weather；更远日期的季节气候使用联网搜索。
- 路线、距离、耗时使用 search_maps。

# Travel Planning Skill
当用户需要创建、修改、延长、缩短、重排或重新规划旅行时，先读取并遵循 travel-planning Skill。
Skill 是规划 procedure；Requirements / Current Plan 的真实状态只能通过 Domain Tools 读取或修改。

# Research delegation
简单 Research 直接使用自己的 search/weather/maps tools。
当任务需要大量、多源 Research，预计会产生很多一次性 Search / Weather / Map 中间结果，
而主 conversation 最终只需要研究结论时，可以通过 task 自动委派给 subagent_type="travel-researcher"。
是否委派由你根据任务判断，不使用天数、搜索次数、关键词等硬编码阈值。
travel-researcher 只做只读 Research；最终 Plan 仍由你结合用户 conversation、Requirements 和 Research Brief 完成。

# Conversation Context
用户对刚生成/刚修改的行程做简单追问，例如“第二天住哪”“为什么这样安排”，
只要当前 conversation context 足够，直接回答。
只有 context 不足、被压缩，或者用户明确要求读取系统最终保存状态时，才调用 get_current_plan。

# Domain Boundary
- update_requirements：外部化当前规划需求，并由代码判断 blocking fields 是否完整。
- get_current_plan：读取 canonical current Plan。
- create_plan / update_plan：Plan 唯一正式提交入口。
- 不允许仅凭聊天记忆声称数据库 Plan 已更新。
- 不编造 user_id、session_id、plan_id 等系统字段。
- Domain Tool 返回失败时，不得声称保存成功。

# Output
create_plan / update_plan 成功后，返回值中的 <final_markdown>...</final_markdown> 已经是确定性 Renderer 的最终用户内容。
原样完整输出其中 Markdown，不再次总结、压缩或重写。

# 边界
- 不向用户暴露内部工具名、subagent 名、user_id、session_id、plan_id 等技术细节。
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
    # Agent scratch files 保持 thread-scoped；Skill 从项目目录只读加载。
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/skills/": FilesystemBackend(
                root_dir=SKILLS_DIR,
                virtual_mode=True,
            ),
        },
    )


def build_agent(*, checkpointer: Checkpointer):
    """构造 Main Deep Agent。checkpointer 由应用生命周期注入。"""
    llm = _build_llm()
    repository = SQLitePlanningRepository()
    domain_tools = build_plan_domain_tools(repository)

    return create_deep_agent(
        state_schema=TravelAgentState,
        model=llm,
        system_prompt=TRAVEL_AGENT_SYSTEM_PROMPT,
        tools=[
            *TRAVEL_TOOLS,
            domain_tools.update_requirements,
            domain_tools.get_current_plan,
            domain_tools.create_plan,
            domain_tools.update_plan,
        ],
        skills=["/skills/"],
        middleware=[PlanCompletionMiddleware()],
        subagents=[build_travel_researcher()],
        backend=_build_backend(),
        permissions=[
            FilesystemPermission(
                operations=["write"],
                paths=["/skills/**"],
                mode="deny",
            ),
        ],
        checkpointer=checkpointer,
        context_schema=TravelRuntimeContext,
        name="travel_agent",
    )
