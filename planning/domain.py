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
        use_requirements_draft: bool = False,
    ) -> PlanDocument:
        current = self.repository.get_current_plan(
            user_id=user_id,
            session_id=session_id,
        )
        if current is None:
            from planning.repository import PlanNotFound
            raise PlanNotFound("当前 session 没有可修改的 Plan")

        # Requirements 的选择必须由调用方显式表达语义，不能因为“碰巧存在一份 draft”
        # 就自动覆盖 current Plan 的 requirements。这样可以避免 stale requirements draft
        # 污染普通修改。
        if use_requirements_draft:
            draft_requirements = self.repository.get_requirements_draft(
                user_id=user_id,
                session_id=session_id,
            )
            if draft_requirements is None:
                raise RequirementsIncomplete(
                    ["destinations", "traveler_count", "duration_or_dates"]
                )
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
        if use_requirements_draft:
            self.repository.clear_requirements_draft(
                user_id=user_id,
                session_id=session_id,
            )
        return document
