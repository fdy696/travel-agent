from planning.models import DayPlan, PlanDraft, TravelRequirements
from planning.renderer import render_plan_markdown


def test_renderer_smoke():
    plan = PlanDraft(
        title="大理1日游",
        requirements=TravelRequirements(
            destinations=["大理"],
            duration_days=1,
            traveler_count=2,
        ),
        schedule=[DayPlan(day=1, city="大理", title="古城慢游")],
    )

    markdown = render_plan_markdown(plan)
    assert "大理1日游" in markdown
    assert "古城慢游" in markdown
