import os

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent import _build_llm
from planning.intelligence import LLMPlanningIntelligence
from planning.models import (
    Activity,
    DayPlan,
    PlanDraft,
    RequirementsPatch,
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
        return "# 研究报告\n\n- 景点：昆明翠湖、大理古城\n"

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
                ),
                DayPlan(
                    day=2,
                    city="大理",
                    activities=[Activity(start_time="10:00", end_time="12:00", title="大理古城", location="大理古城")],
                    transportation=[],
                ),
            ],
        )

    async def generate_modification(self, *, current, instruction, research):
        modified = current.model_copy(update={"title": f"[已修改]{current.title}"})
        return modified


def _seed_plan(repo, *, user_id="u1", session_id="s1"):
    req = TravelRequirements(destinations=["大理"], duration_days=1, traveler_count=2)
    return repo.create_plan(
        user_id=user_id,
        session_id=session_id,
        draft=PlanDraft(
            title="大理1日游",
            requirements=req,
            schedule=[DayPlan(day=1, day_id="d1", city="大理")],
        ),
    ), req


@pytest.mark.asyncio
@pytest.mark.real_api
async def test_real_deepseek_planning_intelligence():
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
    assert research.strip()

    draft = await intelligence.generate_plan(requirements=requirements, research=research)
    assert len(draft.schedule) == requirements.duration_days
    assert draft.requirements.destinations == requirements.destinations


@pytest.mark.asyncio
async def test_workflow_create_collect_then_complete(tmp_path):
    """create 路径：首轮信息不足 → 追问 → 补充 → 生成计划。"""
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    graph = build_planning_graph(intelligence=FakeIntelligence(), repository=repo, checkpointer=InMemorySaver())
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
    content = second["messages"][-1].content
    assert "# 云南2日游" in content
    assert "## Day 1:" in content
    assert "## 📋 出行基础信息" in content

    with repo._connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM plans").fetchone()
        assert row["n"] == 1


@pytest.mark.asyncio
async def test_workflow_no_plan_routes_to_create(tmp_path):
    """session 没有计划时 detect_intent → create 链路。"""
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    graph = build_planning_graph(intelligence=FakeIntelligence(), repository=repo, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "s2"}}
    context = TravelRuntimeContext(user_id="u2", session_id="s2")

    result = await graph.ainvoke(
        {"messages": [HumanMessage("帮我规划云南2日游")]},
        config=config,
        context=context,
    )
    assert "几个人" in result["messages"][-1].content
    assert repo.get_active_plan_for_session(user_id="u2", session_id="s2") is None


@pytest.mark.asyncio
async def test_workflow_detect_intent_routes_to_modify(tmp_path):
    """已有计划时 detect_intent → modify 路径，最终由 Workflow 直接写入 repository。"""
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    _seed_plan(repo, user_id="u1", session_id="s1")

    graph = build_planning_graph(intelligence=FakeIntelligence(), repository=repo, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "s1-modify"}}
    context = TravelRuntimeContext(user_id="u1", session_id="s1")

    result = await graph.ainvoke(
        {"messages": [HumanMessage("第一天不要安排景点，直接休息")]},
        config=config,
        context=context,
    )

    active = repo.get_active_plan_for_session(user_id="u1", session_id="s1")
    assert active is not None
    assert active.title == "[已修改]大理1日游", "修改结果应由 Workflow 直接写入 repository"
    assert "修改" in result["messages"][-1].content


@pytest.mark.asyncio
async def test_workflow_modify_skips_research_for_simple_instruction(tmp_path):
    """简单修改（无研究触发词）应跳过 research，直接进入 generate。"""
    research_called = []

    class TrackingIntelligence(FakeIntelligence):
        async def research(self, requirements):
            research_called.append(True)
            return await super().research(requirements)

    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    _seed_plan(repo, user_id="u1", session_id="s1")

    graph = build_planning_graph(intelligence=TrackingIntelligence(), repository=repo, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "s3"}}
    context = TravelRuntimeContext(user_id="u1", session_id="s1")

    await graph.ainvoke(
        {"messages": [HumanMessage("第一天不要安排景点")]},
        config=config,
        context=context,
    )
    assert not research_called, "简单修改不应触发 research"
