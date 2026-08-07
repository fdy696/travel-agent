"""已交付计划的读取与局部修改工具（v4.1 Phase 4）。

设计要点：
- 用工厂函数注入 repository / intelligence，主 Agent 通过这两个工具直接完成读改，
  不再委派给 travel-planning 子图（那条链路是"从零收集需求 → 生成"的）。
- 修改走乐观锁 + 幂等：Repository.modify_plan(plan_id, expected_version, client_request_id)。
- 工具契约固定返回 JSON 字符串，字段稳定，主 Agent 靠 status/error_code 分支决策，
  避免自由文本让 LLM 误解。
"""
from __future__ import annotations

import json
import uuid

from langchain_core.tools import BaseTool, tool
from langgraph.runtime import get_runtime

from planning.intelligence import PlanningIntelligence
from planning.models import PlanDraft, normalize_plan_draft
from planning.repository import (
    PlanNotFound,
    PlanVersionConflict,
    PlanningRepository,
)
from planning.runtime import TravelRuntimeContext


def _plan_payload(document) -> dict:
    """把 PlanDocument 收敛成对主 Agent 友好的字段子集。"""
    return {
        "plan_id": document.plan_id,
        "version": document.version,
        "parent_version": document.parent_version,
        "title": document.title,
        "schedule": [day.model_dump(mode="json") for day in document.schedule],
        "budget_summary": document.budget_summary.model_dump(mode="json"),
        "assumptions": list(document.assumptions),
        "requirements": document.requirements.model_dump(mode="json"),
    }


def build_plan_tools(
    *,
    repository: PlanningRepository,
    intelligence: PlanningIntelligence,
) -> list[BaseTool]:
    """构造 read_active_plan / modify_travel_plan 两个工具。

    依赖以闭包形式注入，避免全局单例，方便测试替身。
    """

    @tool
    async def read_active_plan() -> str:
        """读取当前会话最近一次已交付的完整行程。

        用户对“我的行程/刚才那个计划/上面的方案”表达修改、追问细节、要求汇总时，
        必须先用这个工具拿到最新版本，再决定下一步。
        返回 JSON：status="ok" 时含 plan_id / version / schedule / budget_summary；
        status="not_found" 表示当前会话还没有生成过完整计划。
        """
        runtime = get_runtime(TravelRuntimeContext)
        ctx = runtime.context
        document = repository.get_active_plan_for_session(
            user_id=ctx.user_id,
            session_id=ctx.session_id,
        )
        if document is None:
            return json.dumps({"status": "not_found"}, ensure_ascii=False)
        return json.dumps(
            {"status": "ok", "plan": _plan_payload(document)},
            ensure_ascii=False,
        )

    @tool
    async def modify_travel_plan(
        plan_id: str,
        expected_version: int,
        instruction: str,
    ) -> str:
        """对已交付行程做局部修改，生成新版本。

        必须先调用 read_active_plan 获得 plan_id 和 version，把 version 作为
        expected_version 传入以启用乐观锁。instruction 使用用户原始表述的自然语言，
        例如“第 2 天去玉龙雪山改成大研古镇”“把预算下调到 6000”。
        不要用它来做“从零规划”，那种场景仍走 travel-planning subagent。

        返回 JSON：
        - status="ok"：修改成功，返回新版本的完整 plan。
        - status="version_conflict"：期望版本已过时；下轮先重新 read_active_plan。
        - status="not_found"：plan_id 不属于当前用户或不存在。
        - status="error"：LLM 生成失败或输入非法，含 error_message。
        """
        runtime = get_runtime(TravelRuntimeContext)
        ctx = runtime.context

        current = repository.get_current_plan(plan_id=plan_id, user_id=ctx.user_id)
        if current is None:
            return json.dumps({"status": "not_found"}, ensure_ascii=False)

        if current.version != expected_version:
            return json.dumps(
                {
                    "status": "version_conflict",
                    "current_version": current.version,
                    "expected_version": expected_version,
                },
                ensure_ascii=False,
            )

        # 把 PlanDocument 剥回 PlanDraft 语义再交给 LLM，避免把 plan_id/version 这些
        # 版本管理字段掺进语义修改上下文。
        current_draft = PlanDraft(
            title=current.title,
            requirements=current.requirements,
            schedule=current.schedule,
            budget_summary=current.budget_summary,
            assumptions=list(current.assumptions),
        )

        try:
            new_draft = await intelligence.modify_plan(
                current=current_draft,
                instruction=instruction,
            )
        except Exception as exc:
            return json.dumps(
                {"status": "error", "error_message": str(exc)},
                ensure_ascii=False,
            )

        # LLM 可能漏填/改乱 ID 或数值类型；沿用 workflow 的归一化保证 ID 稳定、
        # 需求原样不变。
        normalized = normalize_plan_draft(new_draft, current.requirements)
        client_request_id = f"modify:{plan_id}:{expected_version}:{uuid.uuid4().hex}"

        try:
            new_document = repository.modify_plan(
                plan_id=plan_id,
                user_id=ctx.user_id,
                expected_version=expected_version,
                new_draft=normalized,
                client_request_id=client_request_id,
            )
        except PlanVersionConflict as exc:
            return json.dumps(
                {
                    "status": "version_conflict",
                    "current_version": exc.current_version,
                    "expected_version": exc.expected_version,
                },
                ensure_ascii=False,
            )
        except PlanNotFound:
            return json.dumps({"status": "not_found"}, ensure_ascii=False)

        return json.dumps(
            {"status": "ok", "plan": _plan_payload(new_document)},
            ensure_ascii=False,
        )

    return [read_active_plan, modify_travel_plan]
