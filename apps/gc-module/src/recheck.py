from __future__ import annotations

import logging
import time
from pathlib import Path

import config
from collector import load_all_tasks, load_task
from eligibility import row_eligible
from models import ArtifactGroup
from shared.archive_contract import STOP_MARKER, has_stop

_log = logging.getLogger(__name__)


def recheck_group(
    group: ArtifactGroup, *, now: float | None = None
) -> tuple[bool, str]:
    current = time.time() if now is None else now
    reason = group.reason

    if reason == "orphan_download":
        return _recheck_orphan_download(group, now=current)
    if reason == "orphan_stop":
        return _recheck_orphan_stop(group, now=current)

    task_id = group.task_id
    row = load_task(task_id)
    if row is None:
        # DB row vanished: only keep workspace if .stop orphan aged.
        if group.workspace and has_stop(group.workspace):
            return _recheck_orphan_stop(
                ArtifactGroup(
                    task_id=task_id,
                    reason="orphan_stop",
                    workspace=group.workspace,
                ),
                now=current,
            )
        return False, "db_row_missing"

    ok, why = row_eligible(row, now=current)
    if not ok:
        return False, why
    group.db_row = row
    group.reason = why
    # Refresh paths from latest row (result/bin may have moved).
    buf_raw = str(row.get("buf_done_zip") or "").strip()
    group.buf_done = Path(buf_raw) if buf_raw else group.buf_done
    result_csv = str(row.get("result_csv") or "").strip()
    if result_csv:
        primary = Path(result_csv)
        group.result_csvs = [primary, primary.with_name(f"{primary.stem}_T{primary.suffix}")]
    return True, why


def recheck_candidates(
    groups: list[ArtifactGroup], *, now: float | None = None
) -> tuple[list[ArtifactGroup], list[tuple[str, str]]]:
    passed: list[ArtifactGroup] = []
    dropped: list[tuple[str, str]] = []
    for group in groups:
        ok, why = recheck_group(group, now=now)
        if ok:
            # Still need at least one existing path, except we allow empty
            # (nothing to do) — drop empties to avoid noise.
            if not group.existing_paths():
                dropped.append((group.task_id, "nothing_left"))
                continue
            passed.append(group)
        else:
            dropped.append((group.task_id, why))
            _log.info("recheck drop task=%s reason=%s", group.task_id, why)
    return passed, dropped


def _recheck_orphan_stop(
    group: ArtifactGroup, *, now: float
) -> tuple[bool, str]:
    root = group.workspace
    if root is None or not root.is_dir() or not has_stop(root):
        return False, "stop_missing"
    row = load_task(group.task_id)
    if row is not None:
        status = str(row.get("status") or "")
        if status in config.ACTIVE_STATUSES:
            return False, "active"
        ok, why = row_eligible(row, now=now)
        if not ok:
            return False, why
        group.db_row = row
        return True, f"stop_{why}"
    stop_path = root / STOP_MARKER
    try:
        mtime = stop_path.stat().st_mtime
    except OSError:
        return False, "stop_missing"
    if (now - mtime) < config.RETENTION_SEC:
        return False, "orphan_stop_too_young"
    return True, "orphan_stop"


def _recheck_orphan_download(
    group: ArtifactGroup, *, now: float
) -> tuple[bool, str]:
    if not group.downloads:
        return False, "download_missing"
    path = group.downloads[0]
    if not path.is_file():
        return False, "download_missing"
    tasks = load_all_tasks()
    active_filenames = {
        str(t.get("filename") or "").strip()
        for t in tasks
        if str(t.get("status") or "") in config.ACTIVE_STATUSES
        and str(t.get("filename") or "").strip()
    }
    if path.name in active_filenames:
        return False, "download_active"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False, "download_missing"
    if (now - mtime) < config.RETENTION_SEC:
        return False, "orphan_download_too_young"
    return True, "orphan_download"
