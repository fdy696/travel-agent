"""领域存储。

CLI/MVP 使用 SQLite，接口刻意保持领域 Repository 形态；生产环境替换成 PostgreSQL
时，Planning Workflow 不需要改控制流。
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from planning.models import PlanDocument, PlanDraft


class PlanNotFound(Exception):
    """指定 plan 不存在或不属于当前 user_id。"""


class PlanningRepository(Protocol):
    def create_plan(self, *, user_id: str, session_id: str, draft: PlanDraft) -> PlanDocument: ...
    def get_active_plan_for_session(self, *, user_id: str, session_id: str) -> PlanDocument | None: ...
    def get_plan(self, *, plan_id: str, user_id: str) -> PlanDocument | None: ...
    def update_plan(self, *, plan_id: str, user_id: str, new_draft: PlanDraft) -> PlanDocument: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


def default_db_path() -> Path:
    configured = os.getenv("TRAVEL_PLANNING_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / ".data" / "travel_agent.db"


class SQLitePlanningRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or default_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_plans_session
                    ON plans(user_id, session_id, updated_at DESC);
                """
            )

    def create_plan(
        self,
        *,
        user_id: str,
        session_id: str,
        draft: PlanDraft,
    ) -> PlanDocument:
        """为 session 创建当前计划；session 已有计划时直接返回现有内容（幂等）。"""
        with self._connect() as conn:
            existing_row = conn.execute(
                """
                SELECT plan_json FROM plans
                WHERE user_id = ? AND session_id = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (user_id, session_id),
            ).fetchone()
            if existing_row:
                return PlanDocument.model_validate_json(existing_row["plan_json"])

            plan_id = f"plan_{uuid.uuid4().hex[:16]}"
            created_at = _now()
            document = PlanDocument(
                **draft.model_dump(),
                plan_id=plan_id,
                user_id=user_id,
                session_id=session_id,
                created_at=created_at,
            )
            conn.execute(
                """
                INSERT INTO plans (
                    plan_id, user_id, session_id, plan_json, title, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    user_id,
                    session_id,
                    document.model_dump_json(),
                    document.title,
                    created_at.isoformat(),
                    created_at.isoformat(),
                ),
            )
            return document

    def get_plan(self, *, plan_id: str, user_id: str) -> PlanDocument | None:
        with self._connect() as conn:
            return self._get_plan_with_conn(conn, plan_id, user_id)

    def get_active_plan_for_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> PlanDocument | None:
        """按 (user_id, session_id) 取当前计划。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT plan_json FROM plans
                WHERE user_id = ? AND session_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id, session_id),
            ).fetchone()
            return PlanDocument.model_validate_json(row["plan_json"]) if row else None

    def update_plan(
        self,
        *,
        plan_id: str,
        user_id: str,
        new_draft: PlanDraft,
    ) -> PlanDocument:
        """覆盖 current_plan，返回最新内容；不保留历史版本。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT session_id FROM plans WHERE plan_id = ? AND user_id = ?",
                (plan_id, user_id),
            ).fetchone()
            if row is None:
                raise PlanNotFound(f"plan {plan_id} 不存在或无权访问")

            updated_at = _now()
            document = PlanDocument(
                **new_draft.model_dump(),
                plan_id=plan_id,
                user_id=user_id,
                session_id=row["session_id"],
                created_at=updated_at,
            )
            conn.execute(
                """
                UPDATE plans
                SET plan_json = ?, title = ?, updated_at = ?
                WHERE plan_id = ? AND user_id = ?
                """,
                (
                    document.model_dump_json(),
                    document.title,
                    updated_at.isoformat(),
                    plan_id,
                    user_id,
                ),
            )
            conn.commit()
            return document

    def _get_plan_with_conn(
        self,
        conn: sqlite3.Connection,
        plan_id: str,
        user_id: str,
    ) -> PlanDocument | None:
        row = conn.execute(
            "SELECT plan_json FROM plans WHERE plan_id = ? AND user_id = ?",
            (plan_id, user_id),
        ).fetchone()
        return PlanDocument.model_validate_json(row["plan_json"]) if row else None
