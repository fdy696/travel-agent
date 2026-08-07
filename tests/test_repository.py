from planning.models import DayPlan, PlanDraft, TravelRequirements
from planning.repository import SQLitePlanningRepository


def test_task_and_plan_v1_persist(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    task = repo.get_or_create_active_task(user_id="u1", session_id="s1")
    req = TravelRequirements(destinations=["大理"], duration_days=1, traveler_count=2)
    repo.update_requirements(task_id=task.task_id, requirements=req, state="processing")

    draft = PlanDraft(
        title="大理1日游",
        requirements=req,
        schedule=[DayPlan(day=1, day_id="d1", city="大理")],
    )
    plan = repo.create_plan_v1(
        task_id=task.task_id,
        user_id="u1",
        session_id="s1",
        draft=draft,
    )
    assert plan.version == 1
    stored = repo.get_plan_version(plan.plan_id, 1)
    assert stored is not None
    assert stored.title == "大理1日游"

    completed = repo.get_task(task.task_id)
    assert completed is not None
    assert completed.state == "completed"
    assert completed.delivered_plan_id == plan.plan_id
