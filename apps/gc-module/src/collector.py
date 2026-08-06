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
from shared.module_registry import ModuleSpec

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


def load_all_tasks(table: str | None = None) -> list[dict[str, Any]]:
    if table is not None:
        return _load_table(table)
    out: list[dict[str, Any]] = []
    for spec in config.MODULES:
        for row in _load_table(spec.tasks_table):
            row["_module_id"] = spec.module_id
            row["_tasks_table"] = spec.tasks_table
            out.append(row)
    return out


def _load_table(table: str) -> list[dict[str, Any]]:
    conn = _connect_ro()
    if conn is None:
        return []
    try:
        try:
            rows = conn.execute(
                f"""
                SELECT task_id, status, label, filename, error, result_csv,
                       buf_done_zip, finished_at, updated_at, created_at,
                       im_delivered_at, im_chat_id
                FROM {table}
                """
            ).fetchall()
        except sqlite3.OperationalError:
            try:
                rows = conn.execute(
                    f"""
                    SELECT task_id, status, label, filename, error, result_csv,
                           buf_done_zip, finished_at, updated_at, created_at,
                           im_delivered_at
                    FROM {table}
                    """
                ).fetchall()
            except sqlite3.OperationalError:
                _log.warning("ledger table missing or unreadable: %s", table)
                return []
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item.setdefault("im_chat_id", "")
            out.append(item)
        return out
    finally:
        conn.close()


def load_task(
    task_id: str, *, table: str | None = None
) -> dict[str, Any] | None:
    tables = [table] if table else [spec.tasks_table for spec in config.MODULES]
    conn = _connect_ro()
    if conn is None:
        return None
    try:
        for tbl in tables:
            try:
                row = conn.execute(
                    f"""
                    SELECT task_id, status, label, filename, error, result_csv,
                           buf_done_zip, finished_at, updated_at, created_at,
                           im_delivered_at, im_chat_id
                    FROM {tbl} WHERE task_id=?
                    """,
                    (task_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                try:
                    row = conn.execute(
                        f"""
                        SELECT task_id, status, label, filename, error, result_csv,
                               buf_done_zip, finished_at, updated_at, created_at,
                               im_delivered_at
                        FROM {tbl} WHERE task_id=?
                        """,
                        (task_id,),
                    ).fetchone()
                except sqlite3.OperationalError:
                    continue
            if row is None:
                continue
            item = dict(row)
            item.setdefault("im_chat_id", "")
            item["_tasks_table"] = tbl
            return item
        return None
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


def _group_from_row(
    row: dict[str, Any], reason: str, spec: ModuleSpec
) -> ArtifactGroup:
    task_id = str(row.get("task_id") or "")
    workspace = spec.workspace_root / task_id if task_id else None
    buf_raw = str(row.get("buf_done_zip") or "").strip()
    buf_done = Path(buf_raw) if buf_raw else None
    return ArtifactGroup(
        task_id=task_id,
        reason=reason,
        module_id=spec.module_id,
        tasks_table=spec.tasks_table,
        workspace=workspace,
        result_csvs=_result_siblings(row.get("result_csv")),
        buf_done=buf_done,
        db_row=row,
    )


def collect_candidates(*, now: float | None = None) -> list[ArtifactGroup]:
    current = time.time() if now is None else now
    groups: list[ArtifactGroup] = []
    for spec in config.MODULES:
        groups.extend(_collect_for_module(spec, now=current))
    _log.info(
        "mark collected groups=%s modules=%s retention_days=%s",
        len(groups),
        [m.module_id for m in config.MODULES],
        config.RETENTION_DAYS,
    )
    return groups


def _collect_for_module(
    spec: ModuleSpec, *, now: float
) -> list[ArtifactGroup]:
    tasks = _load_table(spec.tasks_table)
    by_id = {str(t.get("task_id") or ""): t for t in tasks if t.get("task_id")}
    active_filenames = {
        str(t.get("filename") or "").strip()
        for t in tasks
        if str(t.get("status") or "") in spec.active_statuses
        and str(t.get("filename") or "").strip()
    }

    groups: list[ArtifactGroup] = []
    seen_task_ids: set[str] = set()

    for row in tasks:
        ok, reason = row_eligible(
            row,
            now=now,
            active_statuses=spec.active_statuses,
            terminal_statuses=spec.terminal_statuses,
        )
        if not ok:
            continue
        task_id = str(row.get("task_id") or "")
        if not task_id or task_id in seen_task_ids:
            continue
        seen_task_ids.add(task_id)
        groups.append(_group_from_row(row, reason, spec))

    for task_key, task_root in iter_task_workspaces(spec.workspace_root):
        if not has_stop(task_root):
            continue
        row = by_id.get(task_key)
        if row is not None:
            status = str(row.get("status") or "")
            if status in spec.active_statuses:
                _log.info(
                    "skip .stop workspace still active: %s (%s)",
                    task_key,
                    spec.module_id,
                )
                continue
            if task_key in seen_task_ids:
                continue
            ok, reason = row_eligible(
                row,
                now=now,
                active_statuses=spec.active_statuses,
                terminal_statuses=spec.terminal_statuses,
            )
            if not ok:
                continue
            seen_task_ids.add(task_key)
            groups.append(_group_from_row(row, f"stop_{reason}", spec))
            continue
        stop_path = task_root / STOP_MARKER
        try:
            mtime = stop_path.stat().st_mtime
        except OSError:
            continue
        if (now - mtime) < config.RETENTION_SEC:
            continue
        if task_key in seen_task_ids:
            continue
        seen_task_ids.add(task_key)
        groups.append(
            ArtifactGroup(
                task_id=task_key,
                reason="orphan_stop",
                module_id=spec.module_id,
                tasks_table=spec.tasks_table,
                workspace=task_root,
            )
        )

    downloads_dir = Path(spec.downloads_dir)
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
            if (now - mtime) < config.RETENTION_SEC:
                continue
            groups.append(
                ArtifactGroup(
                    task_id=f"download:{path.name}",
                    reason="orphan_download",
                    module_id=spec.module_id,
                    tasks_table=spec.tasks_table,
                    downloads=[path],
                )
            )

    _warn_unowned_artifacts(by_id, spec)
    return groups


def _warn_unowned_artifacts(
    by_id: dict[str, dict[str, Any]], spec: ModuleSpec
) -> None:
    known_bins: set[Path] = set()
    known_csvs: set[Path] = set()
    for row in by_id.values():
        buf = str(row.get("buf_done_zip") or "").strip()
        if buf:
            known_bins.add(Path(buf).resolve())
        for path in _result_siblings(row.get("result_csv")):
            known_csvs.add(path.resolve())

    buf_dir = Path(spec.buf_done_dir)
    if buf_dir.is_dir():
        for pattern in ("*.zip", "*.bin"):
            for path in buf_dir.glob(pattern):
                if path.resolve() not in known_bins:
                    _log.warning(
                        "unowned buf_done (not deleted): %s module=%s",
                        path,
                        spec.module_id,
                    )

    result_dir = Path(spec.result_dir)
    if result_dir.is_dir():
        for path in result_dir.glob("*.csv"):
            if path.resolve() not in known_csvs:
                _log.warning(
                    "unowned result csv (not deleted): %s module=%s",
                    path,
                    spec.module_id,
                )
