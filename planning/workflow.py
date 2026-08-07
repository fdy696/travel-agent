"""旅游规划 LangGraph Workflow（Week 2）。

本图不是独立入口，而是作为 CompiledSubAgent 的 runnable 挂到主 Deep Agent 上，
因此它的输入/输出契约由主 agent 侧的 task 工具（SubAgentMiddleware）决定：

输入（每轮调用只有这两样，中间状态跨轮靠 SQLite 恢复）：
- messages：唯一一条 HumanMessage，内容是主 agent 本轮 task 工具调用时填的
  description 参数（见 _last_human_text 的说明）；
- runtime.context：主 agent 的 TravelRuntimeContext(user_id, session_id)，
  由 LangGraph 从父 run 透传，_load_task 用它定位/续接已保存的 planning task。

输出（output_schema=MessagesState 只交还 messages）：
- 最后一条非空 AIMessage 文本会被 middleware 取走，包成 ToolMessage 交还主 agent，
  再由主 agent 转达给用户；本图内部的 task_id / research / draft 等字段不会回传。
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
    ResearchResult,
    TravelRequirements,
    ValidationIssue,
    merge_requirements,
    missing_required_fields,
    normalize_plan_draft,
)
from planning.repository import PlanningRepository
from planning.runtime import TravelRuntimeContext
from planning.validator import validate_plan


class PlanningState(MessagesState, total=False):
    task_id: str
    requirements: TravelRequirements
    missing_fields: list[str]
    research: ResearchResult
    plan_draft: PlanDraft
    validation_issues: list[ValidationIssue]
    repair_count: int
    plan: PlanDocument
    error_code: str
    error_message: str


def _guarded(error_code: str):
    """把节点内异常统一转成 error_code/error_message 返回，收敛重复的 try/except。"""

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
):
    async def load_task(
        state: PlanningState,
        runtime: Runtime[TravelRuntimeContext],
    ) -> dict:
        # runtime.context 是主 agent 调用时的 context= 参数，由 LangGraph 从父 run
        # 透传到本子图（task 工具的入参里并不带它）。跨轮续接也依赖这里：
        # 本子图每次调用都是全新的，不持有对话历史，只有靠 user_id/session_id
        # 从 SQLite 重新加载上次已收集的 requirements 才能继续。
        user_id = runtime.context.user_id
        session_id = runtime.context.session_id
        task = await asyncio.to_thread(
            repository.get_or_create_active_task,
            user_id=user_id,
            session_id=session_id,
        )
        return {
            "task_id": task.task_id,
            "requirements": task.requirements,
            "repair_count": task.repair_count,
            "error_code": "",
            "error_message": "",
        }

    @_guarded("REQUIREMENTS_EXTRACTION_FAILED")
    async def extract_requirements(state: PlanningState) -> dict:
        user_text = _last_human_text(state["messages"])
        patch = await intelligence.extract_requirements(
            user_text=user_text,
            current=state["requirements"],
        )
        return {"requirements": merge_requirements(state["requirements"], patch)}

    async def check_requirements(state: PlanningState) -> dict:
        if state.get("error_code"):
            return {}
        requirements = state["requirements"]
        missing = missing_required_fields(requirements)
        state_label = "collecting" if missing else "processing"
        await asyncio.to_thread(
            repository.update_requirements,
            task_id=state["task_id"],
            requirements=requirements,
            state=state_label,
        )
        return {"missing_fields": missing}

    async def respond_need_more(state: PlanningState) -> dict:
        # 需求不全时提前结束（走 END）。这里返回的 AIMessage 会被 middleware 取为
        # 最后一条非空 AI 文本，包成 ToolMessage 交还主 agent，由主 agent 把这里的
        # 问题转达给用户。用户后续补充的信息，主 agent 会在下一轮重新委派并写进
        # description —— 本子图自己不会记住上一轮问了什么。
        question = _missing_question(state.get("missing_fields", []))
        return {
            "messages": [
                AIMessage(
                    content=(
                        "当前信息还不足以可靠生成完整行程。"
                        f"{question}"
                    )
                )
            ]
        }

    @_guarded("RESEARCH_FAILED")
    async def research(state: PlanningState) -> dict:
        result = await intelligence.research(state["requirements"])
        if not result.has_useful_data():
            return {
                "error_code": "RESEARCH_EMPTY",
                "error_message": "旅游研究没有获得可用数据。",
            }
        return {"research": result}

    @_guarded("PLAN_GENERATION_FAILED")
    async def generate(state: PlanningState) -> dict:
        draft = await intelligence.generate_plan(
            requirements=state["requirements"],
            research=state["research"],
        )
        return {"plan_draft": normalize_plan_draft(draft, state["requirements"])}

    async def validate(state: PlanningState) -> dict:
        issues = validate_plan(state["plan_draft"])
        return {"validation_issues": issues}

    async def repair(state: PlanningState) -> dict:
        next_count = state.get("repair_count", 0) + 1
        try:
            repaired = await intelligence.repair_plan(
                requirements=state["requirements"],
                research=state["research"],
                draft=state["plan_draft"],
                issues=state["validation_issues"],
            )
            repaired = normalize_plan_draft(repaired, state["requirements"])
            await asyncio.to_thread(
                repository.mark_task_state,
                task_id=state["task_id"],
                state="processing",
                repair_count=next_count,
            )
            return {"plan_draft": repaired, "repair_count": next_count}
        except Exception as exc:
            return {
                "repair_count": next_count,
                "error_code": "PLAN_REPAIR_FAILED",
                "error_message": str(exc),
            }

    @_guarded("PLAN_PERSIST_FAILED")
    async def persist(
        state: PlanningState,
        runtime: Runtime[TravelRuntimeContext],
    ) -> dict:
        user_id = runtime.context.user_id
        session_id = runtime.context.session_id
        plan = await asyncio.to_thread(
            repository.create_plan_v1,
            task_id=state["task_id"],
            user_id=user_id,
            session_id=session_id,
            draft=state["plan_draft"],
        )
        return {"plan": plan}

    async def finish(state: PlanningState) -> dict:
        plan = state["plan"]
        return {"messages": [AIMessage(content=_plan_to_markdown(plan))]}

    async def fail(state: PlanningState) -> dict:
        error_code = state.get("error_code") or "PLAN_VALIDATION_FAILED"
        issues = state.get("validation_issues", [])
        detail = state.get("error_message", "")
        if issues:
            detail = "；".join(issue.message for issue in issues[:5])
        await asyncio.to_thread(
            repository.mark_task_state,
            task_id=state["task_id"],
            state="failed",
            error_code=error_code,
            repair_count=state.get("repair_count", 0),
        )
        return {
            "messages": [
                AIMessage(
                    content=(
                        "这次行程规划没有可靠完成。"
                        f"原因：{detail or error_code}。"
                        "你可以补充或调整需求后继续，我会基于已保存的需求重试。"
                    )
                )
            ]
        }

    def _after(state: PlanningState, next_node: str) -> str:
        """节点出错走 fail，否则继续 next_node；收敛四个相同的条件路由。"""
        return "fail" if state.get("error_code") else next_node

    def route_after_check(state: PlanningState) -> Literal["fail", "respond_need_more", "research"]:
        if state.get("error_code"):
            return "fail"
        if state.get("missing_fields"):
            return "respond_need_more"
        return "research"

    def route_after_validate(state: PlanningState) -> Literal["persist", "repair", "fail"]:
        if not state.get("validation_issues"):
            return "persist"
        if state.get("repair_count", 0) < 2:
            return "repair"
        return "fail"

    graph = StateGraph(
        PlanningState,
        context_schema=TravelRuntimeContext,
        output_schema=MessagesState,
    )
    graph.add_node("load_task", load_task)
    graph.add_node("extract_requirements", extract_requirements)
    graph.add_node("check_requirements", check_requirements)
    graph.add_node("respond_need_more", respond_need_more)
    graph.add_node("research", research)
    graph.add_node("generate", generate)
    graph.add_node("validate", validate)
    graph.add_node("repair", repair)
    graph.add_node("persist", persist)
    graph.add_node("finish", finish)
    graph.add_node("fail", fail)

    graph.add_edge(START, "load_task")
    graph.add_edge("load_task", "extract_requirements")
    graph.add_edge("extract_requirements", "check_requirements")
    graph.add_conditional_edges("check_requirements", route_after_check)
    graph.add_edge("respond_need_more", END)
    graph.add_conditional_edges("research", lambda s: _after(s, "generate"))
    graph.add_conditional_edges("generate", lambda s: _after(s, "validate"))
    graph.add_conditional_edges("validate", route_after_validate)
    graph.add_conditional_edges("repair", lambda s: _after(s, "validate"))
    graph.add_conditional_edges("persist", lambda s: _after(s, "finish"))
    graph.add_edge("finish", END)
    graph.add_edge("fail", END)

    return graph.compile()


def _last_human_text(messages: list[BaseMessage]) -> str:
    # 本图每轮只收到一条 HumanMessage：task 工具的 middleware 用 description 参数
    # 构造（见 SubAgentMiddleware._validate_and_prepare_state）。所以取最后一条
    # HumanMessage 就是主 agent 本轮委派时写的 description，里面已包含用户本轮
    # 的原始规划信息 + 主 agent 补上的关键上下文。
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            if isinstance(message.content, str):
                return message.content
            return str(message.content)
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


def _plan_to_markdown(plan: PlanDocument) -> str:
    lines = [
        f"行程已生成：{plan.title}",
        f"计划版本：V{plan.version}",
        "",
    ]
    for day in plan.schedule:
        date_part = f" · {day.date.isoformat()}" if day.date else ""
        lines.append(f"第 {day.day} 天 · {day.city}{date_part}")
        for activity in day.activities:
            lines.append(
                f"- {activity.start_time}-{activity.end_time} {activity.title}（{activity.location}）"
            )
        for transport in day.transportation:
            duration = (
                f"，约 {transport.estimated_duration_minutes} 分钟"
                if transport.estimated_duration_minutes is not None
                else ""
            )
            lines.append(
                f"- 交通：{transport.from_location} → {transport.to_location}，{transport.mode}{duration}"
            )
        if day.accommodation:
            name = f"，{day.accommodation.name}" if day.accommodation.name else ""
            lines.append(
                f"- 住宿：{day.accommodation.area}，{day.accommodation.type}{name}"
            )
        lines.append("")

    lines.append(f"预计人均当地花费：约 {plan.budget_summary.total_cny_per_person} 元")
    if plan.assumptions:
        lines.append("假设/说明：" + "；".join(plan.assumptions))
    return "\n".join(lines)
