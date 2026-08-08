import pytest

from planning.domain import PlanDomainService, RequirementsIncomplete
from planning.models import DayPlan, PlanContent, PlanDraft, RequirementsPatch, TravelRequirements
from planning.repository import SQLitePlanningRepository


def test_requirements_are_code_checked(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    service = PlanDomainService(repo)
    status = service.update_requirements(
        user_id="u1",
        session_id="s1",
        patch=RequirementsPatch(destinations=["云南"], duration_days=5),
        reset=True,
    )
    assert status.complete is False
    assert status.missing_fields == ["traveler_count"]

    status = service.update_requirements(
        user_id="u1",
        session_id="s1",
        patch=RequirementsPatch(traveler_count=2),
    )
    assert status.complete is True


def test_create_plan_combines_content_with_canonical_requirements(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    service = PlanDomainService(repo)
    service.update_requirements(
        user_id="u1",
        session_id="s1",
        patch=RequirementsPatch(destinations=["云南"], duration_days=1, traveler_count=2),
        reset=True,
    )

    # LLM 只能提交 PlanContent，根本没有 requirements 字段可供它篡改或漏填。
    content = PlanContent(
        title="云南1日游",
        schedule=[DayPlan(day=9, city="昆明")],
    )
    saved = service.create_plan(user_id="u1", session_id="s1", content=content)
    assert saved.requirements.destinations == ["云南"]
    assert saved.requirements.traveler_count == 2
    assert saved.schedule[0].day == 1
    assert repo.get_requirements_draft(user_id="u1", session_id="s1") is None


def test_update_plan_preserves_requirements_without_explicit_patch(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    service = PlanDomainService(repo)
    req = TravelRequirements(destinations=["大理"], duration_days=1, traveler_count=2)
    repo.create_plan(
        user_id="u1",
        session_id="s1",
        draft=PlanDraft(title="旧计划", requirements=req, schedule=[DayPlan(day=1, city="大理")]),
    )
    content = PlanContent(
        title="轻松版",
        schedule=[DayPlan(day=1, city="大理")],
    )
    saved = service.update_plan(user_id="u1", session_id="s1", content=content)
    assert saved.requirements == req
    assert saved.title == "轻松版"


def test_stale_complete_requirements_draft_does_not_override_normal_update(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    service = PlanDomainService(repo)

    current_req = TravelRequirements(destinations=["大理"], duration_days=3, traveler_count=2)
    repo.create_plan(
        user_id="u1",
        session_id="s1",
        draft=PlanDraft(
            title="大理3日游",
            requirements=current_req,
            schedule=[DayPlan(day=1, city="大理")],
        ),
    )

    # 模拟之前开始过另一份完整的新旅行需求，但尚未真正替换当前 Plan。
    repo.save_requirements_draft(
        user_id="u1",
        session_id="s1",
        requirements=TravelRequirements(destinations=["北京"], duration_days=5, traveler_count=1),
    )

    updated = service.update_plan(
        user_id="u1",
        session_id="s1",
        content=PlanContent(
            title="大理轻松版",
            schedule=[DayPlan(day=1, city="大理")],
        ),
    )

    assert updated.requirements == current_req
    assert repo.get_requirements_draft(user_id="u1", session_id="s1") is not None
