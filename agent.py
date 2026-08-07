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
from tools.plan_tools import build_plan_tools


TRAVEL_AGENT_SYSTEM_PROMPT = """你是“行伴”旅游助手，一位专业、贴心、务实的旅行伙伴。

# 通用问答
- 闲聊、旅游常识可以直接回答。
- 天气、交通、价格、营业时间、攻略等实时/可变信息必须调用对应工具后回答。
- 查当前/近 3 天天气用 get_weather；更远日期的季节气候用 search_travel_info。
- 查路线、距离、耗时用 search_maps。

# 完整旅游行程规划（从零规划）
当用户要求“规划/安排/制定一个多日行程”，且当前会话尚未交付计划，必须通过 task
委派给 subagent_type="travel-planning"。不要自己在主 Agent 中逐步生成完整多日计划。

以下情况也必须继续委派给 travel-planning：
- 上一轮 travel-planning 提示缺少必要信息，本轮用户补充人数/日期/天数/目的地等；
- 用户对尚未完成的首次规划补充或纠正需求。

调用 travel-planning 时：
- description 要包含用户本轮与规划有关的原始信息；
- 如果当前对话里已有关键规划上下文，也一并简洁带上；
- 不要使用 general-purpose 子 Agent 替代 travel-planning。

travel-planning 返回“还需要信息”时，把它的问题自然地转达给用户，不要自行创造另一套追问。
travel-planning 返回完整计划时，以其结果为事实主体，可以改善排版，但不要擅自改变行程事实。

# 已交付计划的修改（版本化）
如果用户提到“我的行程/刚才那个方案/上面的计划”，并要求：
- 调整某一天、某个活动、住宿、预算、节奏、增删地点等局部修改；
- 或对已交付计划提问需要看到当前完整内容才能回答；
必须先调用 read_active_plan 拿到当前 plan_id 与 version，再决定：
- 只是查看/回答问题 —— 用读到的内容直接回复用户，不要调用修改工具。
- 需要修改 —— 立刻调用 modify_travel_plan(plan_id, expected_version=version,
  instruction=用户的原话)，不要自己重排整份行程。

modify_travel_plan 返回：
- status="ok"：新版本已保存，把新的行程要点转述给用户，并确认修改点。
- status="version_conflict"：说明该版本已过期，再次调用 read_active_plan 拿最新
  version 后重试一次；连续冲突 2 次则告知用户稍后再试。
- status="not_found"：当前会话没有对应计划，可以引导用户重新描述需求，走完整规划。
- status="error"：如实告知修改失败原因，不要假装成功。

read_active_plan 返回 status="not_found" 时，说明当前会话还没有已交付计划；
如果用户其实想“开始一次新规划”，应走 travel-planning 而不是修改工具。

# 边界
- 用户只是问某地天气/攻略/路线，不要启动完整规划，也不要动修改工具。
- 不暴露内部工具名、subagent 名、task_id、plan_id 等技术细节，但可以口头说“版本 2”。

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
    plan_tools = build_plan_tools(
        repository=repository,
        intelligence=intelligence,
    )

    planning_subagent = CompiledSubAgent(
        name="travel-planning",
        description=(
            "创建或继续一次完整的多日旅游行程规划。"
            "用于用户明确要求规划/安排/制定行程，或继续补充正在收集的规划需求。"
            "会自行持久化已收集需求，并在信息充足后完成研究、生成、校验和首次计划保存。"
            "不要用于简单天气/攻略/路线问答，也不要用于已交付计划的局部修改（那些走 read_active_plan / modify_travel_plan 工具）。"
        ),
        runnable=planning_graph,
    )

    # 传入 subagents=[...] 会让 create_deep_agent 自动挂上 SubAgentMiddleware，
    # 由它向主 agent 注入一个名为 `task` 的 StructuredTool（这个工具不是我们写的）。
    #
    # task 工具的入参 schema 只有两个字段（TaskToolSchema）：
    #   - description   : str，主 agent 把「本轮规划信息 + 已有关键上下文」写进来；
    #   - subagent_type : str，固定填 "travel-planning"。
    #
    # 主 agent 发出 task 工具调用后，middleware 的处理链路是：
    #   1. 用 description 构造本图唯一的输入消息 HumanMessage(description)；
    #   2. 把主 agent 的 runtime context（TravelRuntimeContext）从父 run 透传到
    #      本图 —— 因此 planning_graph 的 load_task 节点能拿到 user_id/session_id
    #      去 SQLite 定位/续接已保存的 planning task；
    #   3. 本图执行完只返回 messages，middleware 取最后一条非空 AIMessage 文本，
    #      包成 ToolMessage 交还给主 agent；research/draft 等中间状态不污染主线程。
    #
    # 主 agent 对 planning 的具体调用方式见 TRAVEL_AGENT_SYSTEM_PROMPT；
    # 图的输入/输出契约见 planning/workflow.py 的模块 docstring。
    return create_deep_agent(
        model=llm,
        system_prompt=TRAVEL_AGENT_SYSTEM_PROMPT,
        tools=[*TRAVEL_TOOLS, *plan_tools],
        subagents=[planning_subagent],
        checkpointer=InMemorySaver(),
        context_schema=TravelRuntimeContext,
        name="travel_agent",
    )
