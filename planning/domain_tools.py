"""Deep Agent 可见的 Plan Domain Tools。

Agent 决定何时调用；Tool 内部保证 canonical state / schema / persistence。
模型看不到 user_id/session_id，它们由 ToolRuntime 注入。
"""
import asyncio
import json
from dataclasses import dataclass
from datetime import date

from langchain.tools import ToolException, ToolRuntime
from langchain_core.tools import BaseTool, tool
from pydantic import ValidationError

from planning.domain import PlanDomainService, RequirementsIncomplete
from planning.models import PlanContent, RequirementsPatch
from planning.renderer import render_plan_markdown
from planning.repository import PlanAlreadyExists, PlanNotFound, PlanningRepository
from planning.runtime import TravelRuntimeContext


TravelToolRuntime = ToolRuntime[TravelRuntimeContext]


@dataclass(frozen=True)
class PlanDomainTools:
    update_requirements: BaseTool
    get_current_plan: BaseTool
    create_plan: BaseTool
    update_plan: BaseTool


def _ctx(runtime: TravelToolRuntime) -> TravelRuntimeContext:
    context = runtime.context
    if not isinstance(context, TravelRuntimeContext):
        raise RuntimeError("TravelRuntimeContext 未注入")
    return context


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _validation_error(exc: ValidationError) -> str:
    errors = exc.errors(include_url=False)
    return "ERROR PLAN_SCHEMA_INVALID\n" + _json({"errors": errors[:20]})


def build_plan_domain_tools(repository: PlanningRepository) -> PlanDomainTools:
    service = PlanDomainService(repository)

    @tool
    async def update_requirements(
        patch: dict,
        reset: bool = False,
        runtime: TravelToolRuntime = None,
    ) -> str:
        """更新当前 session 的旅行需求草稿并检查必填项。

        创建/重新规划行程时使用。patch 只放用户本轮明确表达或可直接推导的字段；
        明确开始一个全新规划时 reset=true；上一轮追问后的补充信息 reset=false。

        支持字段：origin, destinations, start_date, end_date, duration_days,
        traveler_count, budget_per_person_cny, pace (节奏，'relaxed'/'comfortable'/'intense'),
        must_visit, exclude, accommodation_preference, notes。
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
            # 这是 patch schema 自身的错误，不是业务逻辑错误
            raise ToolException(f"需求字段更新格式错误: {exc.errors(include_url=False)}") from exc

        return _json(
            {
                "status": "complete" if status.complete else "need_more",
                "missing_fields": status.missing_fields,
                "requirements": status.requirements.model_dump(mode="json"),
            }
        )

    @tool("get_current_plan", return_direct=True)
    async def get_current_plan(runtime: TravelToolRuntime = None) -> str:
        """读取并以 Markdown 格式返回当前 session 的完整旅行计划。

        需要读取 canonical state 时使用；Main Agent 在 conversation context 不足或用户要求确认最终保存状态时调用。
        """
        ctx = _ctx(runtime)
        current = await asyncio.to_thread(
            service.get_current_plan,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
        )
        if current is None:
            return "当前 session 没有已保存的旅行计划。"
        return render_plan_markdown(current.to_draft())

    @tool("create_plan", return_direct=True)
    async def create_plan(plan: dict, runtime: TravelToolRuntime = None) -> str:
        """校验并创建当前 session 的正式 Plan。

        只在新规划需求完整且 Research/规划完成后调用。plan 只包含 PlanContent；
        不要提交 requirements、plan_id、user_id、session_id 或时间戳。
        系统会从数据库读取 canonical requirements，完成校验、归一化、持久化并渲染 Markdown。
        """
        ctx = _ctx(runtime)
        try:
            content = PlanContent.model_validate(plan)
            document = await asyncio.to_thread(
                service.create_plan,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                content=content,
            )
        except ValidationError as exc:
            raise ToolException(_validation_error(exc)) from exc
        except RequirementsIncomplete as exc:
            raise ToolException(
                f"旅行需求收集不完整，缺少字段: {exc.missing_fields}。请先用 update_requirements 补齐。"
            ) from exc
        except PlanAlreadyExists as exc:
            raise ToolException(
                "当前 session 已存在 Plan；如果用户希望重做/替换，请调用 update_plan。"
            ) from exc

        return render_plan_markdown(document.to_draft())

    @tool("update_plan", return_direct=True)
    async def update_plan(
        plan_content: dict,
        requirements_patch: dict | None = None,
        use_requirements_draft: bool = False,
        runtime: TravelToolRuntime = None,
    ) -> str:
        """校验并覆盖当前 session 的 Plan，不保留版本链。

        plan_content 是完整修改后的 PlanContent，不是 patch，也不包含 requirements。
        如果用户明确修改天数/目的地/人数/日期等顶层需求，同时传 requirements_patch；
        普通活动/节奏/住宿内容修改可不传。
        只有“用一份已经完整收集好的新 Requirements 替换当前旅行”时才传 use_requirements_draft=true。
        """
        ctx = _ctx(runtime)
        try:
            content = PlanContent.model_validate(plan_content)
            patch = (
                RequirementsPatch.model_validate(requirements_patch)
                if requirements_patch is not None
                else None
            )
            document = await asyncio.to_thread(
                service.update_plan,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                content=content,
                requirements_patch=patch,
                use_requirements_draft=use_requirements_draft,
            )
        except ValidationError as exc:
            raise ToolException(_validation_error(exc)) from exc
        except RequirementsIncomplete as exc:
            raise ToolException(
                f"旅行需求收集不完整，缺少字段: {exc.missing_fields}。请先用 update_requirements 补齐。"
            ) from exc
        except PlanNotFound as exc:
            raise ToolException(
                "当前 session 没有可修改的旅行计划；如果希望从草稿创建，请调用 create_plan。"
            ) from exc

        return render_plan_markdown(document.to_draft())

    return PlanDomainTools(
        update_requirements=update_requirements,
        get_current_plan=get_current_plan,
        create_plan=create_plan,
        update_plan=update_plan,
    )
