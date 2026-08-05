from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

import config
from eligibility import row_eligible
from models import ArtifactGroup
from shared.archive_contract import STOP_MARKER, has_stop, iter_task_workspaces

_log = logging.getLogger(__name__)


def _connect_ro() -> sqlite3.Connection | None:
    db = Path(config.TASKS_DB)
    if not db.is_file():
        _log.warning("tasks.db missing: %s", db)
        return None
    uri = f"file:{db.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def load_all_tasks() -> list[dict[str, Any]]:
    conn = _connect_ro()
    if conn is None:
        return []
    try:
        try:
            rows = conn.execute(
                """
                SELECT task_id, status, label, filename, error, result_csv,
                       buf_done_zip, finished_at, updated_at, created_at,
                       im_delivered_at, im_chat_id
                FROM tasks
                """
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                """
                SELECT task_id, status, label, filename, error, result_csv,
                       buf_done_zip, finished_at, updated_at, created_at,
                       im_delivered_at
                FROM tasks
                """
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item.setdefault("im_chat_id", "")
            out.append(item)
        return out
    finally:
        conn.close()


def load_task(task_id: str) -> dict[str, Any] | None:
    conn = _connect_ro()
    if conn is None:
        return None
    try:
        try:
            row = conn.execute(
                """
                SELECT task_id, status, label, filename, error, result_csv,
                       buf_done_zip, finished_at, updated_at, created_at,
                       im_delivered_at, im_chat_id
                FROM tasks WHERE task_id=?
                """,
                (task_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = conn.execute(
                """
                SELECT task_id, status, label, filename, error, result_csv,
                       buf_done_zip, finished_at, updated_at, created_at,
                       im_delivered_at
                FROM tasks WHERE task_id=?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item.setdefault("im_chat_id", "")
        return item
    finally:
        conn.close()


def _result_siblings(result_csv: str | Path | None) -> list[Path]:
    if not result_csv:
        return []
    primary = Path(result_csv)
    out = [primary]
    trad = primary.with_name(f"{primary.stem}_T{primary.suffix}")
    if trad != primary:
        out.append(trad)
    return out


def _group_from_row(row: dict[str, Any], reason: str) -> ArtifactGroup:
    task_id = str(row.get("task_id") or "")
    workspace = config.WORKSPACE_ROOT / task_id if task_id else None
    buf_raw = str(row.get("buf_done_zip") or "").strip()
    buf_done = Path(buf_raw) if buf_raw else None
    return ArtifactGroup(
        task_id=task_id,
        reason=reason,
        workspace=workspace,
        result_csvs=_result_siblings(row.get("result_csv")),
        buf_done=buf_done,
        db_row=row,
    )


def collect_candidates(*, now: float | None = None) -> list[ArtifactGroup]:
    current = time.time() if now is None else now
    tasks = load_all_tasks()
    by_id = {str(t.get("task_id") or ""): t for t in tasks if t.get("task_id")}
    active_filenames = {
        str(t.get("filename") or "").strip()
        for t in tasks
        if str(t.get("status") or "") in config.ACTIVE_STATUSES
        and str(t.get("filename") or "").strip()
    }

    groups: list[ArtifactGroup] = []
    seen_task_ids: set[str] = set()

    for row in tasks:
        ok, reason = row_eligible(row, now=current)
        if not ok:
            continue
        task_id = str(row.get("task_id") or "")
        if not task_id or task_id in seen_task_ids:
            continue
        seen_task_ids.add(task_id)
        groups.append(_group_from_row(row, reason))

    # Orphan .stop workspaces (no DB / eligible DB already covered above).
    for task_key, task_root in iter_task_workspaces(config.WORKSPACE_ROOT):
        if not has_stop(task_root):
            continue
        row = by_id.get(task_key)
        if row is not None:
            status = str(row.get("status") or "")
            if status in config.ACTIVE_STATUSES:
                _log.info("skip .stop workspace still active: %s", task_key)
                continue
            if task_key in seen_task_ids:
                continue
            ok, reason = row_eligible(row, now=current)
            if not ok:
                continue
            seen_task_ids.add(task_key)
            groups.append(_group_from_row(row, f"stop_{reason}"))
            continue
        # No DB row: age by .stop mtime.
        stop_path = task_root / STOP_MARKER
        try:
            mtime = stop_path.stat().st_mtime
        except OSError:
            continue
        if (current - mtime) < config.RETENTION_SEC:
            continue
        if task_key in seen_task_ids:
            continue
        seen_task_ids.add(task_key)
        groups.append(
            ArtifactGroup(
                task_id=task_key,
                reason="orphan_stop",
                workspace=task_root,
            )
        )

    # Orphan downloads not referenced by ACTIVE tasks.
    downloads_dir = Path(config.DOWNLOADS_DIR)
    if downloads_dir.is_dir():
        for path in sorted(downloads_dir.iterdir()):
            if not path.is_file():
                continue
            if path.name in active_filenames:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if (current - mtime) < config.RETENTION_SEC:
                continue
            groups.append(
                ArtifactGroup(
                    task_id=f"download:{path.name}",
                    reason="orphan_download",
                    downloads=[path],
                )
            )

    # Unowned result/bin: warn only (never auto-delete).
    _warn_unowned_artifacts(by_id)

    _log.info(
        "mark collected groups=%s retention_days=%s",
        len(groups),
        config.RETENTION_DAYS,
    )
    return groups


def _warn_unowned_artifacts(by_id: dict[str, dict[str, Any]]) -> None:
    known_bins: set[Path] = set()
    known_csvs: set[Path] = set()
    for row in by_id.values():
        buf = str(row.get("buf_done_zip") or "").strip()
        if buf:
            known_bins.add(Path(buf).resolve())
        for path in _result_siblings(row.get("result_csv")):
            known_csvs.add(path.resolve())

    buf_dir = Path(config.BUF_DONE_DIR)
    if buf_dir.is_dir():
        for path in buf_dir.glob("*.bin"):
            if path.resolve() not in known_bins:
                _log.warning("unowned buf_done (not deleted): %s", path)

    result_dir = Path(config.RESULT_DIR)
    if result_dir.is_dir():
        for path in result_dir.glob("*.csv"):
            if path.resolve() not in known_csvs:
                _log.warning("unowned result csv (not deleted): %s", path)
