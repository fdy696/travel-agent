import os

import pytest
from langchain_core.messages import HumanMessage

from agent import _build_llm
from planning.intelligence import LLMPlanningIntelligence
from planning.models import (
    Activity,
    DayPlan,
    PlanDraft,
    RequirementsPatch,
    ResearchResult,
    TravelRequirements,
)
from planning.repository import SQLitePlanningRepository
from planning.workflow import build_planning_graph
from planning.runtime import TravelRuntimeContext


class FakeIntelligence:
    async def extract_requirements(self, *, user_text, current):
        if "云南" in user_text:
            return RequirementsPatch(destinations=["云南"], duration_days=2)
        if "2" in user_text:
            return RequirementsPatch(traveler_count=2)
        return RequirementsPatch()

    async def research(self, requirements):
        return ResearchResult(attractions=["昆明翠湖", "大理古城"], source_notes=["fixture"])

    async def generate_plan(self, *, requirements, research):
        return PlanDraft(
            title="云南2日游",
            requirements=requirements,
            schedule=[
                DayPlan(
                    day=1,
                    city="昆明",
                    activities=[Activity(start_time="09:00", end_time="11:00", title="翠湖", location="翠湖")],
                    transportation=[],
                    estimated_daily_cost_cny_per_person=300,
                ),
                DayPlan(
                    day=2,
                    city="大理",
                    activities=[Activity(start_time="10:00", end_time="12:00", title="大理古城", location="大理古城")],
                    transportation=[],
                    estimated_daily_cost_cny_per_person=400,
                ),
            ],
        )

    async def repair_plan(self, *, requirements, research, draft, issues):
        # 补上跨城市交通。
        from planning.models import Transportation
        draft.schedule[1].transportation = [
            Transportation(
                from_location="昆明",
                to_location="大理",
                mode="高铁",
                estimated_duration_minutes=120,
            )
        ]
        return draft


@pytest.mark.asyncio
@pytest.mark.real_api
async def test_real_deepseek_planning_intelligence():
    """可选的真实 DeepSeek 冒烟测试；需要显式 REAL_DEEPSEEK=1。"""
    if os.getenv("REAL_DEEPSEEK") != "1":
        pytest.skip("设置 REAL_DEEPSEEK=1 才调用真实 DeepSeek API")

    intelligence = LLMPlanningIntelligence(_build_llm())
    requirements = TravelRequirements(
        origin="北京",
        destinations=["云南"],
        duration_days=5,
        traveler_count=2,
        budget_per_person_cny=5000,
        pace="moderate",
        notes="3月，自然风光，舒适档，公共交通",
    )

    patch = await intelligence.extract_requirements(
        user_text="帮我规划云南5日游，2个人，3月，自然风光，舒适，公共交通",
        current=TravelRequirements(),
    )
    assert patch.destinations or patch.duration_days or patch.traveler_count

    research = await intelligence.research(requirements)
    assert research.has_useful_data()

    draft = await intelligence.generate_plan(
        requirements=requirements,
        research=research,
    )
    assert len(draft.schedule) == requirements.duration_days
    assert draft.requirements.destinations == requirements.destinations


@pytest.mark.asyncio
async def test_workflow_collect_then_complete(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    graph = build_planning_graph(intelligence=FakeIntelligence(), repository=repo)
    config = {"configurable": {"thread_id": "s1"}}
    context = TravelRuntimeContext(user_id="u1", session_id="s1")

    first = await graph.ainvoke(
        {"messages": [HumanMessage("帮我规划云南2日游")]},
        config=config,
        context=context,
    )
    assert "几个人" in first["messages"][-1].content

    second = await graph.ainvoke(
        {"messages": [HumanMessage("2个人")]},
        config=config,
        context=context,
    )
    assert "行程已生成" in second["messages"][-1].content

    tasks = []
    # Repository 已完成同 session 的任务；再次 get_or_create 会创建新任务，所以直接检查 DB 中已交付计划。
    with repo._connect() as conn:  # 测试层允许读内部连接验证持久化
        row = conn.execute("SELECT COUNT(*) AS n FROM plans").fetchone()
        assert row["n"] == 1
