import pytest

from planning.domain import PlanDomainService, RequirementsIncomplete
from planning.models import DayPlan, PlanDraft, RequirementsPatch, TravelRequirements
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


def test_create_plan_uses_canonical_requirements(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    service = PlanDomainService(repo)
    service.update_requirements(
        user_id="u1",
        session_id="s1",
        patch=RequirementsPatch(destinations=["云南"], duration_days=1, traveler_count=2),
        reset=True,
    )
    # 模型故意提交了错误 requirements；Domain Service 必须覆盖为 canonical draft。
    llm_draft = PlanDraft(
        title="云南1日游",
        requirements=TravelRequirements(destinations=["北京"], duration_days=1, traveler_count=1),
        schedule=[DayPlan(day=9, city="昆明")],
    )
    saved = service.create_plan(user_id="u1", session_id="s1", draft=llm_draft)
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
    model_output = PlanDraft(
        title="轻松版",
        requirements=TravelRequirements(destinations=["上海"], duration_days=3, traveler_count=8),
        schedule=[DayPlan(day=1, city="大理")],
    )
    saved = service.update_plan(user_id="u1", session_id="s1", draft=model_output)
    assert saved.requirements == req
    assert saved.title == "轻松版"
