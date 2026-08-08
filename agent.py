"""主 Agent 构建（v4.1 / Deep Agents）。

架构：
- Main Agent：Deep Agents ReAct / Tool Calling，持有通用旅游问答工具。
- travel-planning CompiledSubAgent：统一负责行程的创建 + 修改两个场景。
  Workflow 内部通过 detect_intent 节点路由：
    首次规划/补充需求 → extract_requirements → research → generate → persist → finish
    已有计划的修改   → modify（内部 Agent Loop，按需 Research）
- 业务状态：SQLitePlanningRepository（CLI/MVP；生产替换 PostgreSQL）。
- 会话消息：InMemorySaver（CLI/开发；生产需持久化 checkpointer）。
"""
from __future__ import annotations

from deepagents import CompiledSubAgent, create_deep_agent
from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.memory import InMemorySaver

from config import get_settings, require_key
from planning.intelligence import LLMPlanningIntelligence
from planning.repository import SQLitePlanningRepository
from planning.workflow import build_planning_graph
from planning.runtime import TravelRuntimeContext
from tools.agent_tools import TRAVEL_TOOLS


TRAVEL_AGENT_SYSTEM_PROMPT = """你是"行伴"旅游助手，一位专业、贴心、务实的旅行伙伴。

# 通用问答
- 闲聊、旅游常识可以直接回答。
- 天气、交通、价格、营业时间、攻略等实时/可变信息必须调用对应工具后回答。
- 查当前/近 3 天天气用 get_weather；更远日期的季节气候用 search_travel_info。
- 查路线、距离、耗时用 search_maps。

# 行程规划（创建 + 修改，统一委派给 travel-planning）
以下所有情况必须通过 task 委派给 subagent_type="travel-planning"，不要自己生成多日计划：

1. 用户要求"规划/安排/制定一个多日行程"（首次规划）。
2. travel-planning 上一轮提示缺少信息，本轮用户补充了目的地/人数/天数等。
3. 用户要求对已交付行程做任何修改（删活动、调天数、换目的地、改预算、改节奏等）。
4. 用户对已交付行程追问细节，需要完整内容才能回答。

委派方式：
- description 填用户本轮的原始表述 + 必要上下文（"用户已有行程，要求修改：……"）；
- travel-planning 内部会自动判断是首次规划还是修改，你不需要区分。

travel-planning 返回"还需要信息"时，把它的问题自然地转达给用户。
travel-planning 返回完整攻略或修改确认时，**必须原样、完整地转达**，不得概括或改写。

# 边界
- 用户只是问天气/攻略/路线，不要启动规划。
- 不暴露内部工具名、subagent 名、task_id、plan_id 等技术细节。

# 回复风格
- 简洁、直接、口语化。
- 不编造实时事实。
- 一次只追问真正阻塞任务的信息。
"""


def _build_llm() -> ChatDeepSeek:
    return ChatDeepSeek(
        model=get_settings().CHAT_MODEL,
        api_key=require_key("DEEPSEEK_API_KEY"),
        temperature=0.3,
        max_tokens=32000,
        max_retries=3,
        extra_body={
            "thinking": {
                "type": "disabled",
            }
        },
    )


def build_agent():
    llm = _build_llm()
    repository = SQLitePlanningRepository()
    intelligence = LLMPlanningIntelligence(llm)
    planning_graph = build_planning_graph(
        intelligence=intelligence,
        repository=repository,
        checkpointer=InMemorySaver(),
    )

    planning_subagent = CompiledSubAgent(
        name="travel-planning",
        description=(
            "统一负责旅游行程的创建与修改。"
            "用于：首次规划多日行程、补充规划需求、对已交付行程做任何修改。"
            "内部自动判断场景（首次规划 vs 修改），Main Agent 无需区分。"
            "不要用于简单天气/攻略/路线问答。"
        ),
        runnable=planning_graph,
    )

    # SubAgentMiddleware 注入 `task` 工具；调用时 description 是本轮用户任务描述，
    # runtime context（TravelRuntimeContext）从父 run 自动透传到子图。
    return create_deep_agent(
        model=llm,
        system_prompt=TRAVEL_AGENT_SYSTEM_PROMPT,
        tools=TRAVEL_TOOLS,
        subagents=[planning_subagent],
        checkpointer=InMemorySaver(),
        context_schema=TravelRuntimeContext,
        name="travel_agent",
    )
