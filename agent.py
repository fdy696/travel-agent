"""主 Agent 构建（v4.1 / Deep Agents / Week 2）。

Week 2：在 Week 1 通用问答基础上，加入 travel-planning CompiledSubAgent，
内部由 LangGraph Workflow 完成需求收集 → research → generate → validate → repair → persist。

业务 Plan/PlanningTask 使用 Repository 持久化；CLI 阶段默认 SQLite，生产环境再替换 PostgreSQL。
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


TRAVEL_AGENT_SYSTEM_PROMPT = """你是“行伴”旅游助手，一位专业、贴心、务实的旅行伙伴。

# 通用问答
- 闲聊、旅游常识可以直接回答。
- 天气、交通、价格、营业时间、攻略等实时/可变信息必须调用对应工具后回答。
- 查当前/近 3 天天气用 get_weather；更远日期的季节气候用 search_travel_info。
- 查路线、距离、耗时用 search_maps。

# 完整旅游行程规划
当用户要求“规划/安排/制定一个多日行程”，必须通过 task 委派给 subagent_type="travel-planning"。
不要自己在主 Agent 中逐步生成完整多日计划。

以下情况也必须继续委派给 travel-planning：
- 上一轮 travel-planning 提示缺少必要信息，本轮用户补充人数/日期/天数/目的地等；
- 用户对尚未完成的首次规划补充或纠正需求。

调用 travel-planning 时：
- description 要包含用户本轮与规划有关的原始信息；
- 如果当前对话里已有关键规划上下文，也一并简洁带上；
- 不要使用 general-purpose 子 Agent 替代 travel-planning。

travel-planning 返回“还需要信息”时，把它的问题自然地转达给用户，不要自行创造另一套追问。
travel-planning 返回完整计划时，以其结果为事实主体，可以改善排版，但不要擅自改变行程事实。

# 边界
- 用户只是问某地天气/攻略/路线，不要启动完整规划。
- Week 2 暂不支持对已交付计划做版本化局部修改；若用户要求修改，可以说明当前版本尚未开放该能力。
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
        max_tokens=16384,
        max_retries=3,
        extra_body={
            "thinking": {
                "type": "disabled",
            }
        },
    )


def build_agent():
    """构建 Week 2 主 Deep Agent。

    - Main Agent：Deep Agents ReAct / Tool Calling
    - Planning：CompiledSubAgent + LangGraph Workflow
    - 会话消息：InMemorySaver（仅 CLI/开发；生产需持久化 checkpointer）
    - 业务状态：SQLitePlanningRepository（CLI/MVP；生产替换 PostgreSQL）
    """
    llm = _build_llm()
    repository = SQLitePlanningRepository()
    intelligence = LLMPlanningIntelligence(llm)
    planning_graph = build_planning_graph(
        intelligence=intelligence,
        repository=repository,
    )

    planning_subagent = CompiledSubAgent(
        name="travel-planning",
        description=(
            "创建或继续一次完整的多日旅游行程规划。"
            "用于用户明确要求规划/安排/制定行程，或继续补充正在收集的规划需求。"
            "会自行持久化已收集需求，并在信息充足后完成研究、生成、校验和首次计划保存。"
            "不要用于简单天气/攻略/路线问答，也不要用于已交付计划的局部修改。"
        ),
        runnable=planning_graph,
    )

    return create_deep_agent(
        model=llm,
        system_prompt=TRAVEL_AGENT_SYSTEM_PROMPT,
        tools=TRAVEL_TOOLS,
        subagents=[planning_subagent],
        checkpointer=InMemorySaver(),
        context_schema=TravelRuntimeContext,
        name="travel_agent",
    )
