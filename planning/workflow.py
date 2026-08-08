"""旅游规划 LangGraph Workflow（v4.1）。

本图作为 CompiledSubAgent 的 runnable 挂到主 Deep Agent 上。

输入：
- messages：唯一一条 HumanMessage（SubAgentMiddleware 用 task.description 构造）
- runtime.context：TravelRuntimeContext(user_id, session_id)，由父 run 透传

输出（output_schema=MessagesState）：
- 最后一条非空 AIMessage 文本被 middleware 取走，交还主 agent 再转达用户

图结构（两条路径最终汇入共用的 generate → persist → finish）：

                   START
                     │
                     ▼
              detect_intent
              /             \\
          create           modify
            │                │
  extract_requirements  load_current_plan
            │                │
  check_requirements         │ (not_found → fail)
    /         \\              │
need_more    ready            │
   │           └──────┬───────┘
   ▼                  ▼
respond_need_more  research?
   │              /        \\
  END           yes         no
                 │           │
                 ▼           │
             research        │
                 └─────┬─────┘
                       ▼
                    generate   (create: requirements+research / modify: current+instruction+research)
                       │
                    persist    (create: create_plan / modify: update_plan)
                       │
                     finish
                       │
                      END

跨轮续接（create 路径）：
- 需求不全时走 respond_need_more → END，requirements 留在 LangGraph checkpointer
- 下一轮重新进入 detect_intent：此时没有 current_plan，仍走 create，
  extract_requirements 把新输入与已有 requirements 合并
"""
from __future__ import annotations

import asyncio
from functools import wraps
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.runtime import Runtime

from planning.intelligence import PlanningIntelligence
from planning.models import (
    PlanDocument,
    PlanDraft,
    TravelRequirements,
    merge_requirements,
    missing_required_fields,
    normalize_plan_draft,
)
from planning.renderer import render_plan_markdown
from planning.repository import PlanningRepository
from planning.runtime import TravelRuntimeContext


class PlanningState(MessagesState, total=False):
    mode: Literal["create", "modify"]
    requirements: TravelRequirements
    missing_fields: list[str]
    instruction: str
    current_plan: PlanDocument
    research: str
    plan_draft: PlanDraft
    plan: PlanDocument
    error_code: str
    error_message: str


def _guarded(error_code: str):
    def deco(fn):
        @wraps(fn)
        async def wrapper(state: PlanningState, *args, **kwargs):
            try:
                return await fn(state, *args, **kwargs)
            except Exception as exc:
                return {"error_code": error_code, "error_message": str(exc)}
        return wrapper
    return deco


def build_planning_graph(
    *,
    intelligence: PlanningIntelligence,
    repository: PlanningRepository,
    checkpointer=None,
):
    async def detect_intent(
        state: PlanningState,
        runtime: Runtime[TravelRuntimeContext],
    ) -> dict:
        """判断 create vs modify：session 有已交付计划则走 modify，否则走 create。

        只写 mode / instruction / current_plan，不重置 requirements——
        requirements 的持续累积由 extract_requirements 负责。
        """
        user_id = runtime.context.user_id
        session_id = runtime.context.session_id
        current = await asyncio.to_thread(
            repository.get_active_plan_for_session,
            user_id=user_id,
            session_id=session_id,
        )
        instruction = _last_human_text(state["messages"])
        base: dict = {
            "instruction": instruction,
            "error_code": "",
            "error_message": "",
        }
        if current is not None:
            return {**base, "mode": "modify", "current_plan": current}
        return {**base, "mode": "create"}

    @_guarded("REQUIREMENTS_EXTRACTION_FAILED")
    async def extract_requirements(state: PlanningState) -> dict:
        current_req = state.get("requirements") or TravelRequirements()
        patch = await intelligence.extract_requirements(
            user_text=state["instruction"],
            current=current_req,
        )
        return {"requirements": merge_requirements(current_req, patch)}

    async def check_requirements(state: PlanningState) -> dict:
        if state.get("error_code"):
            return {}
        missing = missing_required_fields(state["requirements"])
        return {"missing_fields": missing}

    async def respond_need_more(state: PlanningState) -> dict:
        question = _missing_question(state.get("missing_fields", []))
        return {
            "messages": [AIMessage(content=f"当前信息还不足以可靠生成完整行程。{question}")]
        }

    async def load_current_plan(
        state: PlanningState,
        runtime: Runtime[TravelRuntimeContext],
    ) -> dict:
        """modify 路径专属：从 repository 读取当前计划。

        detect_intent 已经读过一次并存入 state["current_plan"]，
        此节点只做显式的存在性检查，让图结构的 not_found 路由清晰可见。
        """
        current = state.get("current_plan")
        if current is None:
            return {
                "error_code": "NO_CURRENT_PLAN",
                "error_message": "当前会话没有已交付的行程，无法修改。",
            }
        return {}

    @_guarded("RESEARCH_FAILED")
    async def research(state: PlanningState) -> dict:
        if state["mode"] == "create":
            result = await intelligence.research(state["requirements"])
        else:
            current = state["current_plan"].to_draft()
            mod_requirements = TravelRequirements(
                destinations=current.requirements.destinations,
                duration_days=current.requirements.duration_days,
                traveler_count=current.requirements.traveler_count,
                notes=f"修改指令：{state['instruction']}",
            )
            result = await intelligence.research(mod_requirements)
        if not result.strip():
            return {
                "error_code": "RESEARCH_EMPTY",
                "error_message": "旅游研究没有获得可用数据。",
            }
        return {"research": result}

    @_guarded("PLAN_GENERATION_FAILED")
    async def generate(state: PlanningState) -> dict:
        if state["mode"] == "create":
            draft = await intelligence.generate_plan(
                requirements=state["requirements"],
                research=state.get("research", ""),
            )
            normalized = normalize_plan_draft(draft, state["requirements"])
        else:
            draft = await intelligence.generate_modification(
                current=state["current_plan"].to_draft(),
                instruction=state["instruction"],
                research=state.get("research", ""),
            )
            normalized = normalize_plan_draft(draft, draft.requirements)
        return {"plan_draft": normalized}

    @_guarded("PLAN_PERSIST_FAILED")
    async def persist(
        state: PlanningState,
        runtime: Runtime[TravelRuntimeContext],
    ) -> dict:
        user_id = runtime.context.user_id
        session_id = runtime.context.session_id
        if state["mode"] == "create":
            plan = await asyncio.to_thread(
                repository.create_plan,
                user_id=user_id,
                session_id=session_id,
                draft=state["plan_draft"],
            )
        else:
            plan = await asyncio.to_thread(
                repository.update_plan,
                plan_id=state["current_plan"].plan_id,
                user_id=user_id,
                new_draft=state["plan_draft"],
            )
        return {"plan": plan}

    async def finish(state: PlanningState) -> dict:
        plan = state["plan"]
        if state["mode"] == "create":
            content = render_plan_markdown(plan)
        else:
            content = f"行程已按要求修改并保存。\n\n**修改指令**：{state['instruction'][:80]}"
        return {"messages": [AIMessage(content=content)]}

    async def fail(state: PlanningState) -> dict:
        error_code = state.get("error_code") or "UNKNOWN_ERROR"
        detail = state.get("error_message", "")
        return {
            "messages": [
                AIMessage(
                    content=(
                        "这次行程规划未能可靠完成。"
                        f"原因：{detail or error_code}。"
                        "你可以补充或调整需求后继续，我会基于已有信息重试。"
                    )
                )
            ]
        }

    def _after(state: PlanningState, next_node: str) -> str:
        return "fail" if state.get("error_code") else next_node

    def route_after_detect(state: PlanningState) -> Literal["extract_requirements", "load_current_plan"]:
        return "load_current_plan" if state.get("mode") == "modify" else "extract_requirements"

    def route_after_check(state: PlanningState) -> Literal["respond_need_more", "research", "fail"]:
        if state.get("error_code"):
            return "fail"
        return "respond_need_more" if state.get("missing_fields") else "research"

    def route_after_load(state: PlanningState) -> Literal["research", "generate", "fail"]:
        if state.get("error_code"):
            return "fail"
        instruction = state.get("instruction", "")
        needs_research = any(kw in instruction for kw in (
            "延长", "增加", "新增", "加", "天数", "目的地", "香格里拉", "大交通",
            "航班", "高铁", "酒店", "价格", "最新", "天气",
        ))
        return "research" if needs_research else "generate"

    graph = StateGraph(
        PlanningState,
        context_schema=TravelRuntimeContext,
        output_schema=MessagesState,
    )

    graph.add_node("detect_intent", detect_intent)
    graph.add_node("extract_requirements", extract_requirements)
    graph.add_node("check_requirements", check_requirements)
    graph.add_node("respond_need_more", respond_need_more)
    graph.add_node("load_current_plan", load_current_plan)
    graph.add_node("research", research)
    graph.add_node("generate", generate)
    graph.add_node("persist", persist)
    graph.add_node("finish", finish)
    graph.add_node("fail", fail)

    graph.add_edge(START, "detect_intent")
    graph.add_conditional_edges("detect_intent", route_after_detect)

    graph.add_edge("extract_requirements", "check_requirements")
    graph.add_conditional_edges("check_requirements", route_after_check)
    graph.add_edge("respond_need_more", END)

    graph.add_conditional_edges("load_current_plan", route_after_load)

    graph.add_conditional_edges("research", lambda s: _after(s, "generate"))
    graph.add_conditional_edges("generate", lambda s: _after(s, "persist"))
    graph.add_conditional_edges("persist", lambda s: _after(s, "finish"))
    graph.add_edge("finish", END)
    graph.add_edge("fail", END)

    return graph.compile(checkpointer=checkpointer)


def _last_human_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.content if isinstance(message.content, str) else str(message.content)
    raise ValueError("planning subagent 没有收到用户任务描述")


def _missing_question(missing: list[str]) -> str:
    labels = {
        "destinations": "想去哪里",
        "traveler_count": "几个人出行",
        "duration_or_dates": "计划玩几天（或给出起止日期）",
    }
    questions = [labels[item] for item in missing if item in labels]
    if not questions:
        return "请再补充必要的出行信息。"
    if len(questions) == 1:
        return f"请告诉我：{questions[0]}？"
    return "请再告诉我：" + "、".join(questions) + "。"
