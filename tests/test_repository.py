from datetime import timedelta

import pytest

from planning.models import DayPlan, PlanDraft, TravelRequirements
from planning.repository import PlanAlreadyExists, SQLitePlanningRepository


def _draft(title="大理1日游"):
    req = TravelRequirements(destinations=["大理"], duration_days=1, traveler_count=2)
    return PlanDraft(title=title, requirements=req, schedule=[DayPlan(day=1, city="大理")])


def test_requirements_draft_roundtrip(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    req = TravelRequirements(destinations=["云南"], duration_days=5, traveler_count=2)
    repo.save_requirements_draft(user_id="u1", session_id="s1", requirements=req)
    assert repo.get_requirements_draft(user_id="u1", session_id="s1") == req
    repo.clear_requirements_draft(user_id="u1", session_id="s1")
    assert repo.get_requirements_draft(user_id="u1", session_id="s1") is None


def test_one_current_plan_per_session(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    repo.create_plan(user_id="u1", session_id="s1", draft=_draft())
    with pytest.raises(PlanAlreadyExists):
        repo.create_plan(user_id="u1", session_id="s1", draft=_draft("重复"))


def test_update_preserves_created_at_and_changes_updated_at(tmp_path):
    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    first = repo.create_plan(user_id="u1", session_id="s1", draft=_draft())
    updated = repo.update_current_plan(user_id="u1", session_id="s1", new_draft=_draft("新版"))
    assert updated.plan_id == first.plan_id
    assert updated.created_at == first.created_at
    assert updated.updated_at >= first.updated_at
    assert updated.title == "新版"



def test_reads_week03_plan_json_without_updated_at(tmp_path):
    import sqlite3
    from datetime import datetime, timezone

    repo = SQLitePlanningRepository(tmp_path / "travel.db")
    now = datetime.now(timezone.utc).isoformat()
    old_doc = {
        **_draft().model_dump(mode="json"),
        "plan_id": "plan_old",
        "user_id": "u1",
        "session_id": "s1",
        "created_at": now,
    }
    import json
    with repo._connect() as conn:
        conn.execute(
            """
            INSERT INTO plans(plan_id,user_id,session_id,plan_json,title,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            ("plan_old", "u1", "s1", json.dumps(old_doc, ensure_ascii=False), "旧计划", now, now),
        )
    loaded = repo.get_current_plan(user_id="u1", session_id="s1")
    assert loaded is not None
    assert loaded.plan_id == "plan_old"
    assert loaded.updated_at is not None
