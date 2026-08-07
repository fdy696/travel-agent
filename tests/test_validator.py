from planning.models import (
    Activity,
    BudgetSummary,
    DayPlan,
    PlanDraft,
    TravelRequirements,
    normalize_plan_draft,
)
from planning.validator import validate_plan


def _valid_plan() -> PlanDraft:
    req = TravelRequirements(
        destinations=["丽江"],
        duration_days=2,
        traveler_count=2,
        budget_per_person_cny=2000,
        must_visit=["玉龙雪山"],
    )
    draft = PlanDraft(
        title="丽江2日游",
        requirements=req,
        schedule=[
            DayPlan(
                day=1,
                city="丽江",
                activities=[
                    Activity(
                        start_time="09:00",
                        end_time="12:00",
                        title="玉龙雪山",
                        location="玉龙雪山",
                    )
                ],
                estimated_daily_cost_cny_per_person=700,
            ),
            DayPlan(
                day=2,
                city="丽江",
                activities=[
                    Activity(
                        start_time="10:00",
                        end_time="12:00",
                        title="束河古镇",
                        location="束河古镇",
                    )
                ],
                estimated_daily_cost_cny_per_person=500,
            ),
        ],
        budget_summary=BudgetSummary(),
    )
    return normalize_plan_draft(draft, req)


def test_valid_plan_passes():
    assert validate_plan(_valid_plan()) == []


def test_time_conflict_is_rejected():
    plan = _valid_plan()
    plan.schedule[0].activities.append(
        Activity(
            activity_id="d1_a2",
            start_time="11:00",
            end_time="13:00",
            title="冲突活动",
            location="丽江",
        )
    )
    codes = {issue.code for issue in validate_plan(plan)}
    assert "ACTIVITY_TIME_CONFLICT" in codes


def test_budget_overflow_is_rejected():
    plan = _valid_plan()
    plan.schedule[0].estimated_daily_cost_cny_per_person = 2000
    plan.schedule[1].estimated_daily_cost_cny_per_person = 1000
    plan.budget_summary.total_cny_per_person = 3000
    codes = {issue.code for issue in validate_plan(plan)}
    assert "BUDGET_OVERFLOW" in codes
