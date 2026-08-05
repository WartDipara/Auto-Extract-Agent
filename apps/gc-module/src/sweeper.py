from __future__ import annotations

import logging
from pathlib import Path

from models import ArtifactGroup
from shared.archive_contract import rmtree_force

_log = logging.getLogger(__name__)


def _unlink_file(path: Path) -> tuple[str, str]:
    """Return (status, detail) where status is deleted|missing|skipped."""
    if not path.exists():
        return "missing", "already_gone"
    try:
        if path.is_dir():
            rmtree_force(path)
            if path.exists():
                return "skipped", "rmtree_incomplete"
            return "deleted", "ok"
        path.unlink()
        return "deleted", "ok"
    except (PermissionError, OSError) as exc:
        _log.warning("delete skipped path=%s err=%s", path, exc)
        return "skipped", str(exc)


def sweep_group(
    group: ArtifactGroup, *, dry_run: bool
) -> list[dict]:
    """
    Delete buf_done / result / downloads / workspace (existing only).
    Missing members do not fail the group.
    """
    results: list[dict] = []
    for kind, path in group.existing_paths():
        item = {
            "task_id": group.task_id,
            "reason": group.reason,
            "kind": kind,
            "path": str(path),
        }
        if dry_run:
            item["status"] = "dry_run"
            item["detail"] = "would_delete"
            results.append(item)
            _log.info("dry-run %s %s", kind, path)
            continue
        status, detail = _unlink_file(path)
        item["status"] = status
        item["detail"] = detail
        results.append(item)
        _log.info("sweep %s status=%s path=%s", kind, status, path)
    return results


def sweep_all(
    groups: list[ArtifactGroup], *, dry_run: bool
) -> list[dict]:
    out: list[dict] = []
    for group in groups:
        out.extend(sweep_group(group, dry_run=dry_run))
    return out
