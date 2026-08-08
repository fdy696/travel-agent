"""确定性的 Travel Plan Domain Service。

这里不做 LLM reasoning，只负责业务状态边界：
- Requirements draft 的 merge / required-field check
- Current Plan 的 create / update
- PlanDraft Pydantic 校验后的 normalize
"""
from __future__ import annotations

from dataclasses import dataclass

from planning.models import (
    PlanDocument,
    PlanDraft,
    RequirementsPatch,
    TravelRequirements,
    merge_requirements,
    missing_required_fields,
    normalize_plan_draft,
)
from planning.repository import PlanningRepository


class RequirementsIncomplete(Exception):
    def __init__(self, missing_fields: list[str]) -> None:
        super().__init__(f"missing requirements: {missing_fields}")
        self.missing_fields = missing_fields


@dataclass(frozen=True)
class RequirementsStatus:
    requirements: TravelRequirements
    missing_fields: list[str]

    @property
    def complete(self) -> bool:
        return not self.missing_fields


class PlanDomainService:
    def __init__(self, repository: PlanningRepository) -> None:
        self.repository = repository

    def update_requirements(
        self,
        *,
        user_id: str,
        session_id: str,
        patch: RequirementsPatch,
        reset: bool = False,
    ) -> RequirementsStatus:
        current = (
            TravelRequirements()
            if reset
            else self.repository.get_requirements_draft(
                user_id=user_id,
                session_id=session_id,
            )
            or TravelRequirements()
        )
        merged = merge_requirements(current, patch)
        self.repository.save_requirements_draft(
            user_id=user_id,
            session_id=session_id,
            requirements=merged,
        )
        return RequirementsStatus(
            requirements=merged,
            missing_fields=missing_required_fields(merged),
        )

    def get_current_plan(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> PlanDocument | None:
        return self.repository.get_current_plan(
            user_id=user_id,
            session_id=session_id,
        )

    def create_plan(
        self,
        *,
        user_id: str,
        session_id: str,
        draft: PlanDraft,
    ) -> PlanDocument:
        requirements = self.repository.get_requirements_draft(
            user_id=user_id,
            session_id=session_id,
        )
        if requirements is None:
            raise RequirementsIncomplete(["destinations", "traveler_count", "duration_or_dates"])

        missing = missing_required_fields(requirements)
        if missing:
            raise RequirementsIncomplete(missing)

        normalized = normalize_plan_draft(draft, requirements)
        document = self.repository.create_plan(
            user_id=user_id,
            session_id=session_id,
            draft=normalized,
        )
        self.repository.clear_requirements_draft(
            user_id=user_id,
            session_id=session_id,
        )
        return document

    def update_plan(
        self,
        *,
        user_id: str,
        session_id: str,
        draft: PlanDraft,
        requirements_patch: RequirementsPatch | None = None,
    ) -> PlanDocument:
        current = self.repository.get_current_plan(
            user_id=user_id,
            session_id=session_id,
        )
        if current is None:
            from planning.repository import PlanNotFound
            raise PlanNotFound("当前 session 没有可修改的 Plan")

        # 如果 Agent 正在“重新规划一个新行程”，它会先 reset/update requirements。
        # 只有完整 draft 才能替换旧 requirements；不完整 draft 不影响普通修改。
        draft_requirements = self.repository.get_requirements_draft(
            user_id=user_id,
            session_id=session_id,
        )
        use_draft = bool(
            draft_requirements is not None
            and not missing_required_fields(draft_requirements)
        )

        if use_draft:
            canonical_requirements = draft_requirements
        elif requirements_patch is not None:
            canonical_requirements = merge_requirements(
                current.requirements,
                requirements_patch,
            )
        else:
            canonical_requirements = current.requirements

        missing = missing_required_fields(canonical_requirements)
        if missing:
            raise RequirementsIncomplete(missing)

        normalized = normalize_plan_draft(draft, canonical_requirements)
        document = self.repository.update_current_plan(
            user_id=user_id,
            session_id=session_id,
            new_draft=normalized,
        )
        if use_draft:
            self.repository.clear_requirements_draft(
                user_id=user_id,
                session_id=session_id,
            )
        return document
