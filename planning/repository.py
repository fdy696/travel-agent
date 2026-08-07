"""Week 2 本地领域存储。

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

from planning.models import PlanDocument, PlanDraft, PlanningTask, TravelRequirements

_ACTIVE_STATES = ("collecting", "processing", "failed")


class PlanNotFound(Exception):
    """指定 plan 不存在或不属于当前 user_id。"""


class PlanVersionConflict(Exception):
    """乐观锁失败：调用方拿到的 expected_version 与数据库当前版本不一致。"""

    def __init__(self, plan_id: str, current_version: int, expected_version: int) -> None:
        self.plan_id = plan_id
        self.current_version = current_version
        self.expected_version = expected_version
        super().__init__(
            f"plan {plan_id} version conflict: expected {expected_version}, current {current_version}"
        )


class PlanningRepository(Protocol):
    def get_or_create_active_task(self, *, user_id: str, session_id: str) -> PlanningTask: ...
    def update_requirements(self, *, task_id: str, requirements: TravelRequirements, state: str = "collecting") -> PlanningTask: ...
    def mark_task_state(self, *, task_id: str, state: str, error_code: str | None = None, repair_count: int | None = None) -> PlanningTask: ...
    def create_plan_v1(self, *, task_id: str, user_id: str, session_id: str, draft: PlanDraft) -> PlanDocument: ...
    def get_active_plan_for_session(self, *, user_id: str, session_id: str) -> PlanDocument | None: ...
    def get_current_plan(self, *, plan_id: str, user_id: str) -> PlanDocument | None: ...
    def modify_plan(
        self,
        *,
        plan_id: str,
        user_id: str,
        expected_version: int,
        new_draft: PlanDraft,
        client_request_id: str,
    ) -> PlanDocument: ...



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
                CREATE TABLE IF NOT EXISTS planning_tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    requirements_json TEXT NOT NULL,
                    repair_count INTEGER NOT NULL DEFAULT 0,
                    delivered_plan_id TEXT,
                    last_error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_planning_tasks_session_state
                    ON planning_tasks(user_id, session_id, state, updated_at DESC);

                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    current_version INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plan_versions (
                    plan_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    parent_version INTEGER,
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (plan_id, version),
                    FOREIGN KEY (plan_id) REFERENCES plans(plan_id)
                );

                CREATE TABLE IF NOT EXISTS plan_modifications (
                    client_request_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    resulting_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (plan_id) REFERENCES plans(plan_id)
                );
                """
            )

    def get_or_create_active_task(self, *, user_id: str, session_id: str) -> PlanningTask:
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in _ACTIVE_STATES)
            row = conn.execute(
                f"""
                SELECT * FROM planning_tasks
                WHERE user_id = ? AND session_id = ? AND state IN ({placeholders})
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id, session_id, *_ACTIVE_STATES),
            ).fetchone()
            if row:
                return self._task_from_row(row)

            now = _now()
            task = PlanningTask(
                task_id=f"task_{uuid.uuid4().hex[:16]}",
                user_id=user_id,
                session_id=session_id,
                state="collecting",
                requirements=TravelRequirements(),
                created_at=now,
                updated_at=now,
            )
            conn.execute(
                """
                INSERT INTO planning_tasks (
                    task_id, user_id, session_id, state, requirements_json,
                    repair_count, delivered_plan_id, last_error_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.user_id,
                    task.session_id,
                    task.state,
                    task.requirements.model_dump_json(),
                    task.repair_count,
                    task.delivered_plan_id,
                    task.last_error_code,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                ),
            )
            return task

    def get_task(self, task_id: str) -> PlanningTask | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM planning_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return self._task_from_row(row) if row else None

    def update_requirements(
        self,
        *,
        task_id: str,
        requirements: TravelRequirements,
        state: str = "collecting",
    ) -> PlanningTask:
        return self._update_and_read(
            task_id,
            "requirements_json = ?, state = ?, last_error_code = NULL",
            (requirements.model_dump_json(), state),
        )

    def mark_task_state(
        self,
        *,
        task_id: str,
        state: str,
        error_code: str | None = None,
        repair_count: int | None = None,
    ) -> PlanningTask:
        if repair_count is None:
            return self._update_and_read(
                task_id,
                "state = ?, last_error_code = ?",
                (state, error_code),
            )
        return self._update_and_read(
            task_id,
            "state = ?, last_error_code = ?, repair_count = ?",
            (state, error_code, repair_count),
        )

    def _update_and_read(
        self,
        task_id: str,
        set_clause: str,
        params: tuple,
    ) -> PlanningTask:
        """同一连接内 UPDATE 并回读，避免写后重开连接的重复 I/O。"""
        with self._connect() as conn:
            conn.execute(
                f"UPDATE planning_tasks SET {set_clause}, updated_at = ? WHERE task_id = ?",
                (*params, _now().isoformat(), task_id),
            )
            row = conn.execute(
                "SELECT * FROM planning_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"planning task not found: {task_id}")
        return self._task_from_row(row)

    def create_plan_v1(
        self,
        *,
        task_id: str,
        user_id: str,
        session_id: str,
        draft: PlanDraft,
    ) -> PlanDocument:
        """事务性创建 Plan V1；如果任务已完成则幂等返回已交付计划。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task_row = conn.execute(
                "SELECT * FROM planning_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task_row is None:
                raise KeyError(f"planning task not found: {task_id}")

            if task_row["delivered_plan_id"]:
                existing = self._get_plan_version_with_conn(
                    conn,
                    task_row["delivered_plan_id"],
                    1,
                )
                if existing is None:
                    raise RuntimeError("task points to missing delivered plan")
                conn.commit()
                return existing

            plan_id = f"plan_{uuid.uuid4().hex[:16]}"
            created_at = _now()
            document = PlanDocument(
                **draft.model_dump(),
                plan_id=plan_id,
                version=1,
                parent_version=None,
                user_id=user_id,
                session_id=session_id,
                created_at=created_at,
            )
            payload = document.model_dump_json()

            conn.execute(
                """
                INSERT INTO plans (
                    plan_id, user_id, session_id, current_version, title, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    plan_id,
                    user_id,
                    session_id,
                    document.title,
                    created_at.isoformat(),
                    created_at.isoformat(),
                ),
            )
            conn.execute(
                """
                INSERT INTO plan_versions (
                    plan_id, version, parent_version, plan_json, created_at
                ) VALUES (?, 1, NULL, ?, ?)
                """,
                (plan_id, payload, created_at.isoformat()),
            )
            conn.execute(
                """
                UPDATE planning_tasks
                SET state = 'completed', delivered_plan_id = ?, last_error_code = NULL, updated_at = ?
                WHERE task_id = ?
                """,
                (plan_id, created_at.isoformat(), task_id),
            )
            conn.commit()
            return document

    def get_plan_version(self, plan_id: str, version: int) -> PlanDocument | None:
        with self._connect() as conn:
            return self._get_plan_version_with_conn(conn, plan_id, version)

    def get_current_plan(self, *, plan_id: str, user_id: str) -> PlanDocument | None:
        """读取属于 user_id 的 plan 的当前活动版本。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT current_version FROM plans WHERE plan_id = ? AND user_id = ?",
                (plan_id, user_id),
            ).fetchone()
            if row is None:
                return None
            return self._get_plan_version_with_conn(conn, plan_id, row["current_version"])

    def get_active_plan_for_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> PlanDocument | None:
        """按 (user_id, session_id) 取最近一次已交付的活动 plan。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT plan_id, current_version FROM plans
                WHERE user_id = ? AND session_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id, session_id),
            ).fetchone()
            if row is None:
                return None
            return self._get_plan_version_with_conn(
                conn,
                row["plan_id"],
                row["current_version"],
            )

    def modify_plan(
        self,
        *,
        plan_id: str,
        user_id: str,
        expected_version: int,
        new_draft: PlanDraft,
        client_request_id: str,
    ) -> PlanDocument:
        """事务性写入新版本：乐观锁 + 幂等。

        - 幂等：client_request_id 命中已有记录时直接回读对应版本，不重复写。
        - 乐观锁：current_version != expected_version 时抛 PlanVersionConflict。
        - 权限：plan 必须属于当前 user_id，否则抛 PlanNotFound。
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT plan_id, resulting_version FROM plan_modifications WHERE client_request_id = ?",
                (client_request_id,),
            ).fetchone()
            if existing is not None:
                if existing["plan_id"] != plan_id:
                    conn.rollback()
                    raise RuntimeError(
                        f"client_request_id {client_request_id} 已用于其它 plan"
                    )
                document = self._get_plan_version_with_conn(
                    conn,
                    plan_id,
                    existing["resulting_version"],
                )
                conn.commit()
                if document is None:
                    raise RuntimeError("plan_modifications 指向不存在的版本")
                return document

            plan_row = conn.execute(
                "SELECT user_id, session_id, current_version FROM plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if plan_row is None or plan_row["user_id"] != user_id:
                conn.rollback()
                raise PlanNotFound(f"plan {plan_id} 不存在或无权访问")

            current_version = int(plan_row["current_version"])
            if current_version != expected_version:
                conn.rollback()
                raise PlanVersionConflict(
                    plan_id=plan_id,
                    current_version=current_version,
                    expected_version=expected_version,
                )

            new_version = current_version + 1
            created_at = _now()
            document = PlanDocument(
                **new_draft.model_dump(),
                plan_id=plan_id,
                version=new_version,
                parent_version=current_version,
                user_id=user_id,
                session_id=plan_row["session_id"],
                created_at=created_at,
            )
            payload = document.model_dump_json()

            conn.execute(
                """
                INSERT INTO plan_versions (plan_id, version, parent_version, plan_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (plan_id, new_version, current_version, payload, created_at.isoformat()),
            )
            conn.execute(
                """
                UPDATE plans SET current_version = ?, title = ?, updated_at = ?
                WHERE plan_id = ?
                """,
                (new_version, document.title, created_at.isoformat(), plan_id),
            )
            conn.execute(
                """
                INSERT INTO plan_modifications (client_request_id, plan_id, resulting_version, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (client_request_id, plan_id, new_version, created_at.isoformat()),
            )
            conn.commit()
            return document

    def _get_plan_version_with_conn(
        self,
        conn: sqlite3.Connection,
        plan_id: str,
        version: int,
    ) -> PlanDocument | None:
        row = conn.execute(
            "SELECT plan_json FROM plan_versions WHERE plan_id = ? AND version = ?",
            (plan_id, version),
        ).fetchone()
        if row is None:
            return None
        return PlanDocument.model_validate_json(row["plan_json"])

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> PlanningTask:
        return PlanningTask(
            task_id=row["task_id"],
            user_id=row["user_id"],
            session_id=row["session_id"],
            state=row["state"],
            requirements=TravelRequirements.model_validate_json(row["requirements_json"]),
            repair_count=row["repair_count"],
            delivered_plan_id=row["delivered_plan_id"],
            last_error_code=row["last_error_code"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
