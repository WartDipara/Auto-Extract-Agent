from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

import config
from models import ACTIVE_STATUSES, TERMINAL_STATUSES, Task
from shared.archive_contract import utc_now

_log = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _table() -> str:
    return config.TASKS_TABLE


def _seq_key() -> str:
    return config.META_SEQ_KEY


def _db_path() -> Path:
    return Path(config.TASKS_DB)


def open_store() -> None:
    global _conn
    with _lock:
        path = _db_path().resolve()
        if _conn is not None:
            try:
                row = _conn.execute("PRAGMA database_list").fetchone()
                current = Path(str(row[2] or "")).resolve() if row else Path()
            except Exception:
                current = Path()
            if current == path:
                _ensure_columns(_conn)
                return
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        table = _table()
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                task_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                source_file TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL DEFAULT '',
                label TEXT NOT NULL DEFAULT '',
                labels_json TEXT NOT NULL DEFAULT '{{}}',
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                result_csv TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                buf_done_zip TEXT NOT NULL DEFAULT '',
                adb_serial TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT '',
                im_delivered_at TEXT NOT NULL DEFAULT '',
                im_chat_id TEXT NOT NULL DEFAULT '',
                im_sender_id TEXT NOT NULL DEFAULT '',
                im_deliver_error TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_{table}_status ON {table}(status);
            CREATE INDEX IF NOT EXISTS idx_{table}_updated ON {table}(updated_at);
            CREATE INDEX IF NOT EXISTS idx_{table}_url ON {table}(url);
            CREATE INDEX IF NOT EXISTS idx_{table}_source_status ON {table}(source_file, status);
            CREATE INDEX IF NOT EXISTS idx_{table}_undelivered
                ON {table}(im_delivered_at, status);
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        _ensure_columns(conn)
        conn.commit()
        _conn = conn
        _log.info("task_store open %s table=%s", path, table)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    table = _table()
    cols = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if "im_chat_id" not in cols:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN im_chat_id TEXT NOT NULL DEFAULT ''"
        )
    if "im_sender_id" not in cols:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN im_sender_id TEXT NOT NULL DEFAULT ''"
        )
    if "im_deliver_error" not in cols:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN im_deliver_error TEXT NOT NULL DEFAULT ''"
        )


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
        im_chat_id=_row_get(row, "im_chat_id"),
        im_sender_id=_row_get(row, "im_sender_id"),
        im_deliver_error=_row_get(row, "im_deliver_error"),
    )


def _row_get(row: sqlite3.Row, key: str) -> str:
    try:
        return row[key] or ""
    except (KeyError, IndexError):
        return ""


def get_next_seq() -> int:
    key = _seq_key()
    with _lock:
        conn = _require_conn()
        row = conn.execute(
            "SELECT value FROM meta WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, '1')", (key,)
            )
            conn.commit()
            return 1
        return max(1, int(row["value"] or "1"))


def set_next_seq(seq: int) -> None:
    key = _seq_key()
    with _lock:
        conn = _require_conn()
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(seq)),
        )
        conn.commit()


def insert_task(task: Task) -> Task:
    now = utc_now()
    task.created_at = task.created_at or now
    task.updated_at = now
    table = _table()
    with _lock:
        conn = _require_conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                f"""
                INSERT INTO {table} (
                    task_id, url, source_file, filename, label, labels_json,
                    status, error, result_csv, session_id, buf_done_zip, adb_serial,
                    created_at, updated_at, finished_at, im_delivered_at, im_chat_id,
                    im_sender_id, im_deliver_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    task.im_chat_id or "",
                    task.im_sender_id or "",
                    task.im_deliver_error or "",
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
        "im_chat_id",
        "im_sender_id",
        "im_deliver_error",
    }
    patch = {k: v for k, v in fields.items() if k in allowed}
    if not patch:
        return get_task(task_id)

    table = _table()
    with _lock:
        conn = _require_conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE task_id=?", (task_id,)
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
                f"""
                UPDATE {table} SET
                    url=?, source_file=?, filename=?, label=?, labels_json=?,
                    status=?, error=?, result_csv=?, session_id=?, buf_done_zip=?,
                    adb_serial=?, updated_at=?, finished_at=?, im_delivered_at=?,
                    im_chat_id=?, im_sender_id=?, im_deliver_error=?
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
                    task.im_chat_id or "",
                    task.im_sender_id or "",
                    task.im_deliver_error or "",
                    task.task_id,
                ),
            )
            conn.commit()
            return task
        except Exception:
            conn.rollback()
            raise


def get_task(task_id: str) -> Task | None:
    table = _table()
    with _lock:
        conn = _require_conn()
        row = conn.execute(
            f"SELECT * FROM {table} WHERE task_id=?", (task_id,)
        ).fetchone()
        return _row_to_task(row) if row else None


def list_by_status(*statuses: str) -> list[Task]:
    if not statuses:
        return []
    placeholders = ",".join("?" * len(statuses))
    table = _table()
    with _lock:
        conn = _require_conn()
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE status IN ({placeholders}) "
            "ORDER BY updated_at ASC",
            statuses,
        ).fetchall()
        return [_row_to_task(r) for r in rows]


def list_active() -> list[Task]:
    return list_by_status(*ACTIVE_STATUSES)


def list_recent_done(limit: int = 50) -> list[Task]:
    table = _table()
    with _lock:
        conn = _require_conn()
        rows = conn.execute(
            f"""
            SELECT * FROM {table}
            WHERE status IN ({",".join("?" * len(TERMINAL_STATUSES))})
            ORDER BY finished_at DESC, updated_at DESC
            LIMIT ?
            """,
            (*TERMINAL_STATUSES, max(1, int(limit))),
        ).fetchall()
        return [_row_to_task(r) for r in rows]
