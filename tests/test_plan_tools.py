"""read_active_plan / modify_travel_plan 工具的行为测试。

测试策略：
- Repository 用真实 SQLite（tmp_path），确保乐观锁/幂等行为端到端可信；
- Intelligence 用 FakeIntelligence 桩，避免依赖真实 LLM；
- runtime.context 通过 monkeypatch tools.plan_tools.get_runtime 注入。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from planning.models import (
    Activity,
    DayPlan,
    PlanDraft,
    Transportation,
    TravelRequirements,
)
from planning.repository import SQLitePlanningRepository
from planning.runtime import TravelRuntimeContext
from tools import plan_tools


class FakeIntelligence:
    """只需要 modify_plan；其他方法在这里不会被调用。"""

    def __init__(self, transform=None, raises: Exception | None = None):
        self._transform = transform
        self._raises = raises

    async def modify_plan(self, *, current: PlanDraft, instruction: str) -> PlanDraft:
        if self._raises is not None:
            raise self._raises
        if self._transform is not None:
            return self._transform(current, instruction)
        # 默认：只改标题，其它保持
        return current.model_copy(update={"title": f"{current.title}·{instruction}"})


@pytest.fixture
def bootstrap(tmp_path, monkeypatch):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    task = repo.get_or_create_active_task(user_id="u1", session_id="s1")
    req = TravelRequirements(destinations=["丽江"], duration_days=1, traveler_count=2)
    repo.update_requirements(task_id=task.task_id, requirements=req, state="processing")
    plan = repo.create_plan_v1(
        task_id=task.task_id,
        user_id="u1",
        session_id="s1",
        draft=PlanDraft(
            title="丽江1日游",
            requirements=req,
            schedule=[
                DayPlan(
                    day=1,
                    day_id="d1",
                    city="丽江",
                    activities=[
                        Activity(
                            start_time="09:00",
                            end_time="12:00",
                            title="玉龙雪山",
                            location="玉龙雪山",
                        )
                    ],
                    estimated_daily_cost_cny_per_person=500,
                )
            ],
        ),
    )

    ctx = TravelRuntimeContext(user_id="u1", session_id="s1")
    monkeypatch.setattr(
        plan_tools,
        "get_runtime",
        lambda schema=None: SimpleNamespace(context=ctx),
    )
    return repo, plan


@pytest.mark.asyncio
async def test_read_active_plan_returns_current_version(bootstrap):
    repo, plan = bootstrap
    tools = plan_tools.build_plan_tools(repository=repo, intelligence=FakeIntelligence())
    read_tool = next(t for t in tools if t.name == "read_active_plan")

    payload = json.loads(await read_tool.ainvoke({}))
    assert payload["status"] == "ok"
    assert payload["plan"]["plan_id"] == plan.plan_id
    assert payload["plan"]["version"] == 1


@pytest.mark.asyncio
async def test_read_active_plan_not_found_for_new_session(tmp_path, monkeypatch):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    ctx = TravelRuntimeContext(user_id="u1", session_id="empty")
    monkeypatch.setattr(
        plan_tools,
        "get_runtime",
        lambda schema=None: SimpleNamespace(context=ctx),
    )
    tools = plan_tools.build_plan_tools(repository=repo, intelligence=FakeIntelligence())
    read_tool = next(t for t in tools if t.name == "read_active_plan")

    payload = json.loads(await read_tool.ainvoke({}))
    assert payload == {"status": "not_found"}


@pytest.mark.asyncio
async def test_modify_travel_plan_happy_path(bootstrap):
    repo, plan = bootstrap
    tools = plan_tools.build_plan_tools(
        repository=repo,
        intelligence=FakeIntelligence(),
    )
    modify_tool = next(t for t in tools if t.name == "modify_travel_plan")

    payload = json.loads(
        await modify_tool.ainvoke(
            {
                "plan_id": plan.plan_id,
                "expected_version": 1,
                "instruction": "把标题改一改",
            }
        )
    )
    assert payload["status"] == "ok"
    assert payload["plan"]["version"] == 2
    assert payload["plan"]["parent_version"] == 1
    assert "把标题改一改" in payload["plan"]["title"]

    # 持久化确认
    active = repo.get_active_plan_for_session(user_id="u1", session_id="s1")
    assert active is not None and active.version == 2


@pytest.mark.asyncio
async def test_modify_travel_plan_version_conflict(bootstrap):
    repo, plan = bootstrap
    tools = plan_tools.build_plan_tools(
        repository=repo,
        intelligence=FakeIntelligence(),
    )
    modify_tool = next(t for t in tools if t.name == "modify_travel_plan")

    # 先合法把版本提升到 2
    ok = json.loads(
        await modify_tool.ainvoke(
            {
                "plan_id": plan.plan_id,
                "expected_version": 1,
                "instruction": "改一次",
            }
        )
    )
    assert ok["status"] == "ok"

    # 再用旧的 expected_version=1 请求
    conflict = json.loads(
        await modify_tool.ainvoke(
            {
                "plan_id": plan.plan_id,
                "expected_version": 1,
                "instruction": "再改",
            }
        )
    )
    assert conflict["status"] == "version_conflict"
    assert conflict["current_version"] == 2


@pytest.mark.asyncio
async def test_modify_travel_plan_not_found_when_plan_missing(bootstrap):
    repo, _ = bootstrap
    tools = plan_tools.build_plan_tools(
        repository=repo,
        intelligence=FakeIntelligence(),
    )
    modify_tool = next(t for t in tools if t.name == "modify_travel_plan")

    payload = json.loads(
        await modify_tool.ainvoke(
            {
                "plan_id": "plan_does_not_exist",
                "expected_version": 1,
                "instruction": "任意",
            }
        )
    )
    assert payload == {"status": "not_found"}


@pytest.mark.asyncio
async def test_modify_travel_plan_intelligence_error_surfaces(bootstrap):
    repo, plan = bootstrap
    tools = plan_tools.build_plan_tools(
        repository=repo,
        intelligence=FakeIntelligence(raises=RuntimeError("llm boom")),
    )
    modify_tool = next(t for t in tools if t.name == "modify_travel_plan")

    payload = json.loads(
        await modify_tool.ainvoke(
            {
                "plan_id": plan.plan_id,
                "expected_version": 1,
                "instruction": "触发错误",
            }
        )
    )
    assert payload["status"] == "error"
    assert "llm boom" in payload["error_message"]
    # 未写入新版本
    active = repo.get_active_plan_for_session(user_id="u1", session_id="s1")
    assert active is not None and active.version == 1


@pytest.mark.asyncio
async def test_modify_travel_plan_normalizes_ids(bootstrap):
    """LLM 返回时可能漏填 ID；工具必须调 normalize_plan_draft 补齐。"""
    repo, plan = bootstrap

    def transform(current: PlanDraft, instruction: str) -> PlanDraft:
        # 返回一份 ID 全空的新草案
        return PlanDraft(
            title=f"新标题·{instruction}",
            requirements=current.requirements,
            schedule=[
                DayPlan(
                    day=1,
                    city="丽江",
                    activities=[
                        Activity(
                            start_time="09:00",
                            end_time="11:00",
                            title="束河古镇",
                            location="束河古镇",
                        )
                    ],
                    transportation=[
                        Transportation(
                            from_location="丽江古城",
                            to_location="束河古镇",
                            mode="打车",
                            estimated_duration_minutes=20,
                        )
                    ],
                )
            ],
        )

    tools = plan_tools.build_plan_tools(
        repository=repo,
        intelligence=FakeIntelligence(transform=transform),
    )
    modify_tool = next(t for t in tools if t.name == "modify_travel_plan")

    payload = json.loads(
        await modify_tool.ainvoke(
            {
                "plan_id": plan.plan_id,
                "expected_version": 1,
                "instruction": "换掉玉龙雪山",
            }
        )
    )
    assert payload["status"] == "ok"
    day = payload["plan"]["schedule"][0]
    assert day["day_id"] == "d1"
    assert day["activities"][0]["activity_id"] == "d1_a1"
    assert day["transportation"][0]["trans_id"] == "d1_t1"
