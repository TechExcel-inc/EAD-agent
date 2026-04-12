"""
SQLite-backed project template and execution storage.

Follows the same patterns as hermes_state.SessionDB:
- WAL mode for concurrent readers + single writer
- Application-level retry with jitter on write contention
- Thread-safe via lock
"""

import json
import logging
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from .models import (
    ExecutionStatus,
    ProjectExecute,
    ProjectTemplate,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR = Path.home() / ".hermes" / "projects"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "projects.db"

_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    last_modified_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS executions (
    id TEXT PRIMARY KEY,
    linked_template_id TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (linked_template_id) REFERENCES templates(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_executions_template ON executions(linked_template_id);
CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);

CREATE TABLE IF NOT EXISTS active_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_WRITE_MAX_RETRIES = 10
_WRITE_RETRY_MIN_S = 0.020
_WRITE_RETRY_MAX_S = 0.150


class ProjectStore:
    """SQLite-backed project template and execution storage."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=1.0,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.executescript(_SCHEMA_SQL)
                row = self._conn.execute(
                    "SELECT version FROM schema_version"
                ).fetchone()
                if row is None:
                    self._conn.execute(
                        "INSERT INTO schema_version (version) VALUES (?)",
                        (_SCHEMA_VERSION,),
                    )
                self._conn.commit()
            except BaseException:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                raise

    def _execute_write(self, fn):
        last_err = None
        for attempt in range(_WRITE_MAX_RETRIES):
            try:
                with self._lock:
                    self._conn.execute("BEGIN IMMEDIATE")
                    try:
                        result = fn(self._conn)
                        self._conn.commit()
                    except BaseException:
                        try:
                            self._conn.rollback()
                        except Exception:
                            pass
                        raise
                return result
            except sqlite3.OperationalError as exc:
                err_msg = str(exc).lower()
                if "locked" in err_msg or "busy" in err_msg:
                    last_err = exc
                    delay = random.uniform(_WRITE_RETRY_MIN_S, _WRITE_RETRY_MAX_S)
                    time.sleep(delay)
                    continue
                raise
        raise last_err

    # ------------------------------------------------------------------
    # Template CRUD
    # ------------------------------------------------------------------

    def list_templates(self) -> List[ProjectTemplate]:
        rows = self._conn.execute(
            "SELECT data FROM templates ORDER BY last_modified_at DESC"
        ).fetchall()
        return [ProjectTemplate.model_validate_json(r["data"]) for r in rows]

    def get_template(self, template_id: str) -> Optional[ProjectTemplate]:
        row = self._conn.execute(
            "SELECT data FROM templates WHERE id = ?", (template_id,)
        ).fetchone()
        if not row:
            return None
        return ProjectTemplate.model_validate_json(row["data"])

    def create_template(self, template: ProjectTemplate) -> ProjectTemplate:
        data = template.model_dump_json()

        def _write(conn):
            conn.execute(
                "INSERT INTO templates (id, data, created_at, last_modified_at) VALUES (?, ?, ?, ?)",
                (template.id, data, template.created_at, template.last_modified_at),
            )

        self._execute_write(_write)
        return template

    def update_template(self, template_id: str, **fields) -> Optional[ProjectTemplate]:
        template = self.get_template(template_id)
        if not template:
            return None

        for key, value in fields.items():
            if hasattr(template, key):
                setattr(template, key, value)

        template.last_modified_at = int(time.time() * 1000)
        data = template.model_dump_json()

        def _write(conn):
            conn.execute(
                "UPDATE templates SET data = ?, last_modified_at = ? WHERE id = ?",
                (data, template.last_modified_at, template_id),
            )

        self._execute_write(_write)
        return template

    def delete_template(self, template_id: str) -> bool:
        template = self.get_template(template_id)
        if not template:
            return False

        def _write(conn):
            conn.execute("DELETE FROM executions WHERE linked_template_id = ?", (template_id,))
            conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))

        self._execute_write(_write)
        return True

    def get_active_template_id(self) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM active_state WHERE key = 'active_template_id'"
        ).fetchone()
        return row["value"] if row else None

    def set_active_template_id(self, template_id: Optional[str]) -> None:
        def _write(conn):
            if template_id is None:
                conn.execute("DELETE FROM active_state WHERE key = 'active_template_id'")
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO active_state (key, value) VALUES (?, ?)",
                    ("active_template_id", template_id),
                )

        self._execute_write(_write)

    # ------------------------------------------------------------------
    # Execution CRUD
    # ------------------------------------------------------------------

    def list_executions(
        self, template_id: Optional[str] = None, status: Optional[str] = None
    ) -> List[ProjectExecute]:
        query = "SELECT data FROM executions WHERE 1=1"
        params = []
        if template_id:
            query += " AND linked_template_id = ?"
            params.append(template_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [ProjectExecute.model_validate_json(r["data"]) for r in rows]

    def get_execution(self, execution_id: str) -> Optional[ProjectExecute]:
        row = self._conn.execute(
            "SELECT data FROM executions WHERE id = ?", (execution_id,)
        ).fetchone()
        if not row:
            return None
        return ProjectExecute.model_validate_json(row["data"])

    def create_execution(self, execution: ProjectExecute) -> ProjectExecute:
        data = execution.model_dump_json()
        created_at = execution.start_time or int(time.time() * 1000)

        def _write(conn):
            conn.execute(
                "INSERT INTO executions (id, linked_template_id, data, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (execution.id, execution.linked_template_id, data, execution.status.value, created_at),
            )

        self._execute_write(_write)
        return execution

    def update_execution(self, execution_id: str, **fields) -> Optional[ProjectExecute]:
        execution = self.get_execution(execution_id)
        if not execution:
            return None

        for key, value in fields.items():
            if hasattr(execution, key):
                setattr(execution, key, value)

        data = execution.model_dump_json()

        def _write(conn):
            conn.execute(
                "UPDATE executions SET data = ?, status = ? WHERE id = ?",
                (data, execution.status.value, execution_id),
            )

        self._execute_write(_write)
        return execution

    def delete_execution(self, execution_id: str) -> bool:
        execution = self.get_execution(execution_id)
        if not execution:
            return False

        def _write(conn):
            conn.execute("DELETE FROM executions WHERE id = ?", (execution_id,))

        self._execute_write(_write)
        return True

    # ------------------------------------------------------------------
    # Bulk / utility
    # ------------------------------------------------------------------

    def get_active_executions(self) -> List[ProjectExecute]:
        return self.list_executions(status=ExecutionStatus.RUNNING.value) + \
               self.list_executions(status=ExecutionStatus.PENDING.value)
