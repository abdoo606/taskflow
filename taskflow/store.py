"""SQLite persistence layer with a versioned schema and explicit transactions."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from .models import Priority, Status, Task, utcnow

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    priority   TEXT    NOT NULL DEFAULT 'medium',
    status     TEXT    NOT NULL DEFAULT 'todo',
    tags       TEXT    NOT NULL DEFAULT '',
    due        TEXT,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
"""


class TaskStore:
    """Thin, testable wrapper around a SQLite connection."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    # -- infrastructure ---------------------------------------------------
    def _migrate(self) -> None:
        with self._transaction() as cur:
            cur.executescript(SCHEMA)
            cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TaskStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- mapping ----------------------------------------------------------
    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            title=row["title"],
            priority=Priority(row["priority"]),
            status=Status(row["status"]),
            tags=tuple(t for t in row["tags"].split(",") if t),
            due=row["due"],
            created_at=row["created_at"],
        )

    # -- commands ---------------------------------------------------------
    def add(self, task: Task) -> Task:
        with self._transaction() as cur:
            cur.execute(
                "INSERT INTO tasks (title, priority, status, tags, due, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    task.title,
                    task.priority.value,
                    task.status.value,
                    ",".join(task.tags),
                    task.due,
                    task.created_at,
                ),
            )
            task.id = int(cur.lastrowid)
        return task

    def update_status(self, task_id: int, status: Status) -> bool:
        with self._transaction() as cur:
            cur.execute("UPDATE tasks SET status = ? WHERE id = ?", (status.value, task_id))
            return cur.rowcount > 0

    def delete(self, task_id: int) -> bool:
        with self._transaction() as cur:
            cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cur.rowcount > 0

    # -- queries ----------------------------------------------------------
    def get(self, task_id: int) -> Task | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list(
        self,
        *,
        status: Status | None = None,
        tag: str | None = None,
        search: str | None = None,
    ) -> list[Task]:
        sql = "SELECT * FROM tasks WHERE 1=1"
        params: list[object] = []
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        if tag:
            # tags are stored comma-separated with sentinel commas for exact matching
            sql += " AND (',' || tags || ',') LIKE ?"
            params.append(f"%,{tag},%")
        if search:
            sql += " AND title LIKE ?"
            params.append(f"%{search}%")
        rows = self._conn.execute(sql, params).fetchall()
        return sorted((self._row_to_task(r) for r in rows), key=Task.sort_key)

    def counts_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def overdue(self) -> list[Task]:
        return [t for t in self.list(status=None) if t.is_overdue]

    def bulk_add(self, tasks: Iterable[Task]) -> int:
        n = 0
        for task in tasks:
            self.add(task)
            n += 1
        return n


def default_db_path() -> Path:
    return Path.home() / ".taskflow" / "tasks.db"
