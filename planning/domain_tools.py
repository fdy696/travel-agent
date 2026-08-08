"""Deep Agent 可见的 Plan Domain Tools。

Agent 决定何时调用；Tool 内部保证 canonical state / schema / persistence。
模型看不到 user_id/session_id，它们由 ToolRuntime 注入。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, tool
from pydantic import ValidationError

from planning.domain import PlanDomainService, RequirementsIncomplete
from planning.models import PlanContent, PlanDraft, RequirementsPatch, TravelRequirements
from planning.renderer import render_plan_markdown
from planning.repository import PlanAlreadyExists, PlanNotFound, PlanningRepository
from planning.runtime import TravelRuntimeContext


@dataclass(frozen=True)
class PlanDomainTools:
    update_requirements: BaseTool
    get_current_plan: BaseTool
    create_plan: BaseTool
    update_plan: BaseTool


def _ctx(runtime: ToolRuntime) -> TravelRuntimeContext:
    context = runtime.context
    if not isinstance(context, TravelRuntimeContext):
        raise RuntimeError("TravelRuntimeContext 未注入")
    return context


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _validation_error(exc: ValidationError) -> str:
    errors = exc.errors(include_url=False)
    return "ERROR PLAN_SCHEMA_INVALID\n" + _json({"errors": errors[:20]})


def _final_markdown(event: str, markdown: str) -> str:
    return (
        f"SUCCESS {event}\n"
        "<final_markdown>\n"
        f"{markdown.rstrip()}\n"
        "</final_markdown>"
    )


def build_plan_domain_tools(repository: PlanningRepository) -> PlanDomainTools:
    service = PlanDomainService(repository)

    @tool
    async def update_requirements(
        patch: dict,
        reset: bool = False,
        runtime: ToolRuntime = None,
    ) -> str:
        """更新当前 session 的旅行需求草稿并检查必填项。

        创建/重新规划行程时使用。patch 只放用户本轮明确表达或可直接推导的字段；
        明确开始一个全新规划时 reset=true；上一轮追问后的补充信息 reset=false。

        支持字段：origin, destinations, start_date, end_date, duration_days,
        traveler_count, budget_per_person_cny, pace, must_visit, exclude,
        accommodation_preference, notes。
        """
        ctx = _ctx(runtime)
        try:
            parsed = RequirementsPatch.model_validate(patch)
            status = await asyncio.to_thread(
                service.update_requirements,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                patch=parsed,
                reset=reset,
            )
        except ValidationError as exc:
            return "ERROR REQUIREMENTS_SCHEMA_INVALID\n" + _json({"errors": exc.errors(include_url=False)})

        output = {
            "status": "complete" if status.complete else "need_more",
            "missing_fields": status.missing_fields,
            "requirements": status.requirements.model_dump(mode="json"),
        }
        if status.complete:
            output["state"] = {"plan_task_status": "pending", "completion_retry": 0}

        return _json(output)

    @tool
    async def get_current_plan(runtime: ToolRuntime = None) -> str:
        """读取当前 session 的 canonical Plan。

        需要读取 canonical state 时使用；Main Agent 在 conversation context 不足或用户要求确认最终保存状态时调用。
        返回的是完整 PlanDraft，不暴露 plan_id 等内部元数据。
        """
        ctx = _ctx(runtime)
        current = await asyncio.to_thread(
            service.get_current_plan,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
        )
        if current is None:
            return _json({"status": "not_found", "message": "当前 session 没有已保存的旅行计划。"})
        return _json(
            {
                "status": "success",
                "plan": current.to_draft().model_dump(mode="json"),
            }
        )

    @tool
    async def create_plan(plan: dict, runtime: ToolRuntime = None) -> str:
        """校验并创建当前 session 的正式 Plan。

        只在新规划需求完整且 Research/规划完成后调用。plan 必须是包含规划核心内容的对象；
        它将被校验为 PlanContent（具体结构见 travel-planning Skill 的 references/plan-schema.md）。
        系统会自动从数据库读取 canonical requirements 并覆盖、分配稳定 ID、持久化并渲染 Markdown。
        """
        ctx = _ctx(runtime)
        try:
            # Per user feedback, the model should only provide content.
            # The code is responsible for assembling the final object.
            content = PlanContent.model_validate(plan)

            # The domain service will fetch and override the requirements anyway.
            # We create a draft with dummy requirements to satisfy the type hint.
            draft = PlanDraft(requirements=TravelRequirements(), **content.model_dump())

            document = await asyncio.to_thread(
                service.create_plan,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                draft=draft,
            )
        except ValidationError as exc:
            return _validation_error(exc)
        except RequirementsIncomplete as exc:
            return "ERROR REQUIREMENTS_INCOMPLETE\n" + _json({"missing_fields": exc.missing_fields})
        except PlanAlreadyExists:
            return "ERROR PLAN_ALREADY_EXISTS\n当前 session 已存在 Plan；如果用户希望重做/替换，请调用 update_plan。"

        markdown = render_plan_markdown(document.to_draft())
        output = {
            "state": {"plan_task_status": "committed"},
            "markdown": _final_markdown("PLAN_CREATED", markdown),
        }
        return _json(output)

    @tool
    async def update_plan(
        plan_content: dict,
        requirements_patch: dict | None = None,
        use_requirements_draft: bool = False,
        runtime: ToolRuntime = None,
    ) -> str:
        """校验并覆盖当前 session 的 Plan，不保留版本链。

        plan_content 必须是修改后的核心内容对象（将被校验为 PlanContent），而不是 patch。
        如果用户明确修改了天数/目的地/人数/日期等顶层需求，同时传 requirements_patch；
        普通活动/节奏/住宿内容修改可不传。
        只有“用一份已经完整收集好的新 Requirements 替换当前旅行”时才显式传 use_requirements_draft=true；
        """
        ctx = _ctx(runtime)
        try:
            content = PlanContent.model_validate(plan_content)
            patch = RequirementsPatch.model_validate(requirements_patch) if requirements_patch is not None else None

            draft = PlanDraft(requirements=TravelRequirements(), **content.model_dump())

            document = await asyncio.to_thread(
                service.update_plan,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                draft=draft,
                requirements_patch=patch,
                use_requirements_draft=use_requirements_draft,
            )
        except ValidationError as exc:
            return _validation_error(exc)
        except RequirementsIncomplete as exc:
            return "ERROR REQUIREMENTS_INCOMPLETE\n" + _json({"missing_fields": exc.missing_fields})
        except PlanNotFound:
            return "ERROR NO_CURRENT_PLAN\n当前 session 没有可修改的旅行计划。"

        markdown = render_plan_markdown(document.to_draft())
        output = {
            "state": {"plan_task_status": "committed"},
            "markdown": _final_markdown("PLAN_UPDATED", markdown),
        }
        return _json(output)

    return PlanDomainTools(
        update_requirements=update_requirements,
        get_current_plan=get_current_plan,
        create_plan=create_plan,
        update_plan=update_plan,
    )
