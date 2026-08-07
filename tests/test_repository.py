from planning.models import DayPlan, PlanDraft, TravelRequirements
from planning.repository import (
    PlanNotFound,
    PlanVersionConflict,
    SQLitePlanningRepository,
)
import pytest


def _bootstrap_plan(repo, *, user_id="u1", session_id="s1"):
    task = repo.get_or_create_active_task(user_id=user_id, session_id=session_id)
    req = TravelRequirements(destinations=["大理"], duration_days=1, traveler_count=2)
    repo.update_requirements(task_id=task.task_id, requirements=req, state="processing")
    draft = PlanDraft(
        title="大理1日游",
        requirements=req,
        schedule=[DayPlan(day=1, day_id="d1", city="大理")],
    )
    plan = repo.create_plan_v1(
        task_id=task.task_id,
        user_id=user_id,
        session_id=session_id,
        draft=draft,
    )
    return plan, req


def test_task_and_plan_v1_persist(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    plan, _ = _bootstrap_plan(repo)
    assert plan.version == 1
    stored = repo.get_plan_version(plan.plan_id, 1)
    assert stored is not None
    assert stored.title == "大理1日游"

    active = repo.get_active_plan_for_session(user_id="u1", session_id="s1")
    assert active is not None
    assert active.plan_id == plan.plan_id
    assert active.version == 1


def test_get_current_plan_scoped_by_user(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    plan, _ = _bootstrap_plan(repo, user_id="u1")

    assert repo.get_current_plan(plan_id=plan.plan_id, user_id="u1") is not None
    # 其他用户看不到
    assert repo.get_current_plan(plan_id=plan.plan_id, user_id="u2") is None


def test_modify_plan_creates_new_version(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    plan, req = _bootstrap_plan(repo)

    new_draft = PlanDraft(
        title="大理1日游 v2",
        requirements=req,
        schedule=[DayPlan(day=1, day_id="d1", city="大理古城")],
    )
    updated = repo.modify_plan(
        plan_id=plan.plan_id,
        user_id="u1",
        expected_version=1,
        new_draft=new_draft,
        client_request_id="req-1",
    )
    assert updated.version == 2
    assert updated.parent_version == 1
    assert updated.title == "大理1日游 v2"

    active = repo.get_active_plan_for_session(user_id="u1", session_id="s1")
    assert active is not None and active.version == 2
    # 历史版本仍可读
    assert repo.get_plan_version(plan.plan_id, 1) is not None


def test_modify_plan_idempotent_same_request_id(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    plan, req = _bootstrap_plan(repo)

    new_draft = PlanDraft(
        title="改一次",
        requirements=req,
        schedule=[DayPlan(day=1, day_id="d1", city="大理")],
    )
    first = repo.modify_plan(
        plan_id=plan.plan_id,
        user_id="u1",
        expected_version=1,
        new_draft=new_draft,
        client_request_id="req-1",
    )
    second = repo.modify_plan(
        plan_id=plan.plan_id,
        user_id="u1",
        expected_version=1,
        new_draft=new_draft,
        client_request_id="req-1",
    )
    assert first.version == second.version == 2
    # 只应有一条 modification 记录，plan 仍在 v2
    active = repo.get_active_plan_for_session(user_id="u1", session_id="s1")
    assert active is not None and active.version == 2


def test_modify_plan_version_conflict(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    plan, req = _bootstrap_plan(repo)

    # 先合法提升到 v2
    repo.modify_plan(
        plan_id=plan.plan_id,
        user_id="u1",
        expected_version=1,
        new_draft=PlanDraft(
            title="v2",
            requirements=req,
            schedule=[DayPlan(day=1, day_id="d1", city="大理")],
        ),
        client_request_id="req-a",
    )

    with pytest.raises(PlanVersionConflict) as exc:
        repo.modify_plan(
            plan_id=plan.plan_id,
            user_id="u1",
            expected_version=1,  # 已过期
            new_draft=PlanDraft(
                title="v3",
                requirements=req,
                schedule=[DayPlan(day=1, day_id="d1", city="大理")],
            ),
            client_request_id="req-b",
        )
    assert exc.value.current_version == 2
    assert exc.value.expected_version == 1


def test_modify_plan_rejects_other_user(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    plan, req = _bootstrap_plan(repo, user_id="u1")

    with pytest.raises(PlanNotFound):
        repo.modify_plan(
            plan_id=plan.plan_id,
            user_id="attacker",
            expected_version=1,
            new_draft=PlanDraft(
                title="试探",
                requirements=req,
                schedule=[DayPlan(day=1, day_id="d1", city="大理")],
            ),
            client_request_id="req-x",
        )
