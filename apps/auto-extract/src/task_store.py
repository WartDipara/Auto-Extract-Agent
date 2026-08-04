from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

import config
from models import TERMINAL_STATUSES, Task
from shared.archive_contract import utc_now

_log = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _db_path() -> Path:
    return Path(config.TASKS_DB)


def open_store() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        path = _db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                source_file TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL DEFAULT '',
                label TEXT NOT NULL DEFAULT '',
                labels_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                result_csv TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                buf_done_zip TEXT NOT NULL DEFAULT '',
                adb_serial TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT '',
                im_delivered_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at);
            CREATE INDEX IF NOT EXISTS idx_tasks_url ON tasks(url);
            CREATE INDEX IF NOT EXISTS idx_tasks_source_status ON tasks(source_file, status);
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.commit()
        _conn = conn
        _log.info("task_store open %s", path)


def _require_conn() -> sqlite3.Connection:
    if _conn is None:
        open_store()
    assert _conn is not None
    return _conn


def _row_to_task(row: sqlite3.Row) -> Task:
    labels: dict = {}
    raw = row["labels_json"] or "{}"
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            labels = parsed
    except json.JSONDecodeError:
        labels = {}
    return Task(
        task_id=row["task_id"],
        url=row["url"],
        source_file=row["source_file"] or "",
        filename=row["filename"] or "",
        labels=labels,
        label=row["label"] or "",
        status=row["status"],
        error=row["error"] or "",
        result_csv=row["result_csv"] or "",
        session_id=row["session_id"] or "",
        buf_done_zip=row["buf_done_zip"] or "",
        adb_serial=row["adb_serial"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
        finished_at=row["finished_at"] or "",
        im_delivered_at=row["im_delivered_at"] or "",
    )


def get_next_seq() -> int:
    with _lock:
        conn = _require_conn()
        row = conn.execute(
            "SELECT value FROM meta WHERE key='next_seq'"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('next_seq', '1')"
            )
            conn.commit()
            return 1
        return max(1, int(row["value"] or "1"))


def set_next_seq(seq: int) -> None:
    with _lock:
        conn = _require_conn()
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('next_seq', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(seq),),
        )
        conn.commit()


def insert_task(task: Task) -> Task:
    now = utc_now()
    task.created_at = task.created_at or now
    task.updated_at = now
    with _lock:
        conn = _require_conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, url, source_file, filename, label, labels_json,
                    status, error, result_csv, session_id, buf_done_zip, adb_serial,
                    created_at, updated_at, finished_at, im_delivered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.url,
                    task.source_file or "",
                    task.filename or "",
                    task.label or "",
                    json.dumps(task.labels or {}, ensure_ascii=False),
                    task.status,
                    task.error or "",
                    task.result_csv or "",
                    task.session_id or "",
                    task.buf_done_zip or "",
                    task.adb_serial or "",
                    task.created_at,
                    task.updated_at,
                    task.finished_at or "",
                    task.im_delivered_at or "",
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return task


def update_task(task_id: str, **fields: Any) -> Task | None:
    allowed = {
        "url",
        "source_file",
        "filename",
        "label",
        "labels",
        "status",
        "error",
        "result_csv",
        "session_id",
        "buf_done_zip",
        "adb_serial",
        "finished_at",
        "im_delivered_at",
    }
    patch = {k: v for k, v in fields.items() if k in allowed}
    if not patch:
        return get_task(task_id)

    with _lock:
        conn = _require_conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            task = _row_to_task(row)
            for key, value in patch.items():
                if key == "labels":
                    task.labels = value if isinstance(value, dict) else {}
                else:
                    setattr(task, key, value)
            now = utc_now()
            task.updated_at = now
            if task.status in TERMINAL_STATUSES and not task.finished_at:
                task.finished_at = now
            conn.execute(
                """
                UPDATE tasks SET
                    url=?, source_file=?, filename=?, label=?, labels_json=?,
                    status=?, error=?, result_csv=?, session_id=?, buf_done_zip=?,
                    adb_serial=?, updated_at=?, finished_at=?, im_delivered_at=?
                WHERE task_id=?
                """,
                (
                    task.url,
                    task.source_file or "",
                    task.filename or "",
                    task.label or "",
                    json.dumps(task.labels or {}, ensure_ascii=False),
                    task.status,
                    task.error or "",
                    task.result_csv or "",
                    task.session_id or "",
                    task.buf_done_zip or "",
                    task.adb_serial or "",
                    task.updated_at,
                    task.finished_at or "",
                    task.im_delivered_at or "",
                    task.task_id,
                ),
            )
            conn.commit()
            return task
        except Exception:
            conn.rollback()
            raise


def get_task(task_id: str) -> Task | None:
    with _lock:
        conn = _require_conn()
        row = conn.execute(
            "SELECT * FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        return _row_to_task(row) if row else None


def list_by_status(*statuses: str) -> list[Task]:
    if not statuses:
        return []
    placeholders = ",".join("?" * len(statuses))
    with _lock:
        conn = _require_conn()
        rows = conn.execute(
            f"SELECT * FROM tasks WHERE status IN ({placeholders}) "
            "ORDER BY updated_at ASC",
            statuses,
        ).fetchall()
        return [_row_to_task(r) for r in rows]


def list_active() -> list[Task]:
    return list_by_status(
        "queued",
        "downloaded",
        "patched",
        "on_device",
        "device_done",
        "on_extract",
        "extract_done",
    )


def list_recent_done(limit: int = 50) -> list[Task]:
    with _lock:
        conn = _require_conn()
        rows = conn.execute(
            f"""
            SELECT * FROM tasks
            WHERE status IN ({",".join("?" * len(TERMINAL_STATUSES))})
            ORDER BY finished_at DESC, updated_at DESC
            LIMIT ?
            """,
            (*TERMINAL_STATUSES, max(1, int(limit))),
        ).fetchall()
        return [_row_to_task(r) for r in rows]
