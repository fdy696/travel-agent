from planning.models import DayPlan, PlanDraft, TravelRequirements
from planning.repository import PlanNotFound, SQLitePlanningRepository
import pytest


def _bootstrap_plan(repo, *, user_id="u1", session_id="s1"):
    req = TravelRequirements(destinations=["大理"], duration_days=1, traveler_count=2)
    draft = PlanDraft(
        title="大理1日游",
        requirements=req,
        schedule=[DayPlan(day=1, day_id="d1", city="大理")],
    )
    plan = repo.create_plan(user_id=user_id, session_id=session_id, draft=draft)
    return plan, req


def test_plan_persist(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    plan, _ = _bootstrap_plan(repo)
    stored = repo.get_plan(plan_id=plan.plan_id, user_id="u1")
    assert stored is not None
    assert stored.title == "大理1日游"

    active = repo.get_active_plan_for_session(user_id="u1", session_id="s1")
    assert active is not None
    assert active.plan_id == plan.plan_id


def test_get_plan_scoped_by_user(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    plan, _ = _bootstrap_plan(repo, user_id="u1")

    assert repo.get_plan(plan_id=plan.plan_id, user_id="u1") is not None
    assert repo.get_plan(plan_id=plan.plan_id, user_id="u2") is None


def test_create_plan_idempotent(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    plan1, req = _bootstrap_plan(repo)
    plan2 = repo.create_plan(
        user_id="u1",
        session_id="s1",
        draft=PlanDraft(title="重复创建", requirements=req, schedule=[]),
    )
    assert plan1.plan_id == plan2.plan_id
    assert plan2.title == "大理1日游"


def test_update_plan_overwrites_current(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    plan, req = _bootstrap_plan(repo)

    new_draft = PlanDraft(
        title="大理1日游 v2",
        requirements=req,
        schedule=[DayPlan(day=1, day_id="d1", city="大理古城")],
    )
    updated = repo.update_plan(plan_id=plan.plan_id, user_id="u1", new_draft=new_draft)
    assert updated.plan_id == plan.plan_id
    assert updated.title == "大理1日游 v2"

    active = repo.get_active_plan_for_session(user_id="u1", session_id="s1")
    assert active is not None
    assert active.title == "大理1日游 v2"


def test_update_plan_rejects_other_user(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    plan, req = _bootstrap_plan(repo, user_id="u1")

    with pytest.raises(PlanNotFound):
        repo.update_plan(
            plan_id=plan.plan_id,
            user_id="attacker",
            new_draft=PlanDraft(
                title="试探",
                requirements=req,
                schedule=[DayPlan(day=1, day_id="d1", city="大理")],
            ),
        )
