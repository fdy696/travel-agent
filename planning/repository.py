"""Travel Plan 领域存储。

当前版本仍使用 SQLite 作为 CLI/MVP persistence；Agent 架构与 Repository 接口解耦，
后续替换 PostgreSQL 不需要改变 Agent 的 reasoning loop。

Repository 只保存系统事实，不负责语义规划：
- planning_requirements: 当前 session 尚未完成的需求草稿
- plans: 当前 session 唯一的 current Plan
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from planning.models import PlanDocument, PlanDraft, TravelRequirements


class PlanNotFound(Exception):
    """当前 Plan 不存在。"""


class PlanAlreadyExists(Exception):
    """当前 session 已经存在 Plan，应使用 update_current_plan。"""


class PlanningRepository(Protocol):
    def get_requirements_draft(self, *, user_id: str, session_id: str) -> TravelRequirements | None: ...
    def save_requirements_draft(self, *, user_id: str, session_id: str, requirements: TravelRequirements) -> None: ...
    def clear_requirements_draft(self, *, user_id: str, session_id: str) -> None: ...

    def create_plan(self, *, user_id: str, session_id: str, draft: PlanDraft) -> PlanDocument: ...
    def get_current_plan(self, *, user_id: str, session_id: str) -> PlanDocument | None: ...
    def update_current_plan(self, *, user_id: str, session_id: str, new_draft: PlanDraft) -> PlanDocument: ...


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

                CREATE UNIQUE INDEX IF NOT EXISTS uq_plans_user_session
                    ON plans(user_id, session_id);

                CREATE TABLE IF NOT EXISTS planning_requirements (
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    requirements_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, session_id)
                );
                """
            )

    # ---------- Requirements Draft ----------

    def get_requirements_draft(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> TravelRequirements | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT requirements_json
                FROM planning_requirements
                WHERE user_id = ? AND session_id = ?
                """,
                (user_id, session_id),
            ).fetchone()
        return TravelRequirements.model_validate_json(row["requirements_json"]) if row else None

    def save_requirements_draft(
        self,
        *,
        user_id: str,
        session_id: str,
        requirements: TravelRequirements,
    ) -> None:
        now = _now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO planning_requirements (
                    user_id, session_id, requirements_json, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, session_id)
                DO UPDATE SET
                    requirements_json = excluded.requirements_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, session_id, requirements.model_dump_json(), now),
            )

    def clear_requirements_draft(self, *, user_id: str, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM planning_requirements WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )

    # ---------- Current Plan ----------

    def create_plan(
        self,
        *,
        user_id: str,
        session_id: str,
        draft: PlanDraft,
    ) -> PlanDocument:
        """创建 current Plan。session 已有 Plan 时拒绝，避免误覆盖。"""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM plans WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            ).fetchone()
            if existing:
                raise PlanAlreadyExists("当前 session 已存在 Plan，请使用 update_current_plan")

            plan_id = f"plan_{uuid.uuid4().hex[:16]}"
            now = _now()
            document = PlanDocument(
                **draft.model_dump(),
                plan_id=plan_id,
                user_id=user_id,
                session_id=session_id,
                created_at=now,
                updated_at=now,
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
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            return document

    def get_current_plan(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> PlanDocument | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT plan_json, plan_id, user_id, session_id, created_at, updated_at
                FROM plans
                WHERE user_id = ? AND session_id = ?
                LIMIT 1
                """,
                (user_id, session_id),
            ).fetchone()
        return self._row_to_document(row) if row else None

    # 兼容 week_03 旧调用名称，重构完成后可删除。
    def get_active_plan_for_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> PlanDocument | None:
        return self.get_current_plan(user_id=user_id, session_id=session_id)

    def update_current_plan(
        self,
        *,
        user_id: str,
        session_id: str,
        new_draft: PlanDraft,
    ) -> PlanDocument:
        """覆盖 current Plan；不创建版本链。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT plan_id, created_at
                FROM plans
                WHERE user_id = ? AND session_id = ?
                """,
                (user_id, session_id),
            ).fetchone()
            if row is None:
                raise PlanNotFound("当前 session 没有可修改的 Plan")

            updated_at = _now()
            created_at = datetime.fromisoformat(row["created_at"])
            document = PlanDocument(
                **new_draft.model_dump(),
                plan_id=row["plan_id"],
                user_id=user_id,
                session_id=session_id,
                created_at=created_at,
                updated_at=updated_at,
            )
            conn.execute(
                """
                UPDATE plans
                SET plan_json = ?, title = ?, updated_at = ?
                WHERE user_id = ? AND session_id = ?
                """,
                (
                    document.model_dump_json(),
                    document.title,
                    updated_at.isoformat(),
                    user_id,
                    session_id,
                ),
            )
            conn.commit()
            return document

    def _row_to_document(self, row: sqlite3.Row) -> PlanDocument:
        # 历史 week_03 的 plan_json 只有 created_at、没有 updated_at。
        # 这里把 JSON 当作 PlanDraft 内容读取，metadata 一律以表列为 canonical。
        payload = json.loads(row["plan_json"])
        for key in ("plan_id", "user_id", "session_id", "created_at", "updated_at"):
            payload.pop(key, None)
        draft = PlanDraft.model_validate(payload)
        return PlanDocument(
            **draft.model_dump(),
            plan_id=row["plan_id"],
            user_id=row["user_id"],
            session_id=row["session_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
