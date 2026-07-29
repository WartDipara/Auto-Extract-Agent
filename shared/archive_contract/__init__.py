"""
Shared workspace contract for auto-extract (A) and archive-followup (B).

Per-task layout: workspace/<task_key>/{decoded,hotfix,outputs}
Markers:
  .module_a_done  — A finished successfully
  .followup_lock  — B running
  .stop           — task discarded; interrupt OpenCode if running; purge later
No zip archives.
"""

from __future__ import annotations

import json
import logging
import shutil
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "2"

OPENCODE_OUTPUT_NAME = "tests.csv"
OPENCODE_EXPORT_NAME = "opencode_session.json"
META_FILENAME = "meta.json"
MODULE_A_DONE = ".module_a_done"
FOLLOWUP_LOCK = ".followup_lock"
STOP_MARKER = ".stop"

_log = logging.getLogger(__name__)


class FollowupLockedError(RuntimeError):
    """Task workspace is locked by an in-progress followup."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def auto_extract_paths(repo_root: Path) -> dict[str, Path]:
    app = Path(repo_root) / "apps" / "auto-extract"
    workspace = app / "workspace"
    return {
        "app_root": app,
        "workspace": workspace,
        "state": app / "state",
        "queue_json": app / "state" / "queue.json",
        "result": app / "result",
        "opencode_sessions": app / "state" / "opencode_sessions.jsonl",
    }


def task_workspace(workspace_root: Path, task_key: str) -> Path:
    return Path(workspace_root) / task_key


def task_layout(task_root: Path) -> dict[str, Path]:
    root = Path(task_root)
    outputs = root / "outputs"
    return {
        "root": root,
        "decoded": root / "decoded",
        "hotfix": root / "hotfix",
        "outputs": outputs,
        "tests_csv": outputs / OPENCODE_OUTPUT_NAME,
        "opencode_export": outputs / OPENCODE_EXPORT_NAME,
        "meta": root / META_FILENAME,
        "module_a_done": root / MODULE_A_DONE,
        "followup_lock": root / FOLLOWUP_LOCK,
        "stop": root / STOP_MARKER,
    }


def _on_rm_error(func, path, exc_info):
    try:
        Path(path).chmod(stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def rmtree_force(path: Path) -> None:
    if not path.exists():
        return
    for _ in range(5):
        try:
            shutil.rmtree(path, onerror=_on_rm_error)
        except OSError:
            pass
        if not path.exists():
            return
        time.sleep(0.3)


def has_module_a_done(task_root: Path) -> bool:
    return (Path(task_root) / MODULE_A_DONE).is_file()


def has_followup_lock(task_root: Path) -> bool:
    return (Path(task_root) / FOLLOWUP_LOCK).is_file()


def has_stop(task_root: Path) -> bool:
    return (Path(task_root) / STOP_MARKER).is_file()


def mark_module_a_done(task_root: Path) -> None:
    (Path(task_root) / MODULE_A_DONE).write_text("", encoding="utf-8")


def mark_stop(task_root: Path) -> Path:
    """Mark task as discarded. Running OpenCode polls this path and exits."""
    path = Path(task_root) / STOP_MARKER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def purge_stopped_workspaces(workspace_root: Path) -> list[str]:
    """
    Delete task workspaces that carry .stop.
    Skips when .followup_lock is present (B still writing).
    Returns deleted task_key list.
    """
    deleted: list[str] = []
    for task_key, task_root in iter_task_workspaces(workspace_root):
        if not has_stop(task_root):
            continue
        if has_followup_lock(task_root):
            _log.warning("skip purge (followup lock): %s", task_key)
            continue
        _log.info("purging stopped workspace: %s", task_key)
        rmtree_force(task_root)
        if not task_root.exists():
            deleted.append(task_key)
        else:
            _log.error("purge failed (still exists): %s", task_key)
    return deleted


def acquire_followup_lock(task_root: Path) -> None:
    root = Path(task_root)
    if not has_module_a_done(root):
        raise RuntimeError(f"module A not done: {root.name}")
    lock = root / FOLLOWUP_LOCK
    if lock.is_file():
        raise RuntimeError(f"followup already running: {root.name}")
    lock.write_text("", encoding="utf-8")


def release_followup_lock(task_root: Path) -> None:
    lock = Path(task_root) / FOLLOWUP_LOCK
    if lock.is_file():
        lock.unlink()


def reset_task_workspace(workspace_root: Path, task_key: str) -> Path:
    """
    Create a fresh task workspace. If the directory already exists, wipe it
    (overwrite). Refuses when .followup_lock is present.
    """
    root = task_workspace(workspace_root, task_key)
    if has_followup_lock(root):
        raise FollowupLockedError(f"followup in progress: {task_key}")
    if root.exists():
        rmtree_force(root)
        _log.info("task workspace wiped for overwrite: %s", task_key)
    layout = task_layout(root)
    for key in ("decoded", "hotfix", "outputs"):
        layout[key].mkdir(parents=True, exist_ok=True)
    return root


def write_meta(task_root: Path, data: dict[str, Any]) -> Path:
    path = Path(task_root) / META_FILENAME
    payload = dict(data)
    payload["contract_version"] = CONTRACT_VERSION
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_meta(task_root: Path) -> dict[str, Any] | None:
    path = Path(task_root) / META_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def iter_task_workspaces(workspace_root: Path):
    """Yield (task_key, task_root) for immediate child directories."""
    root = Path(workspace_root)
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            yield child.name, child


def find_task_root_by_session(
    workspace_root: Path, session_id: str
) -> Path | None:
    sid = (session_id or "").strip()
    if not sid:
        return None
    for _key, task_root in iter_task_workspaces(workspace_root):
        meta = read_meta(task_root)
        if meta and str(meta.get("session_id") or "").strip() == sid:
            return task_root
    return None


def default_result_csv_path(result_dir: Path, task_key: str, label: str) -> Path:
    safe = "".join(c if c not in '\\/:*?"<>|' else "_" for c in (label or "").strip())
    name = f"{task_key}_{safe}.csv" if safe else f"{task_key}.csv"
    return Path(result_dir) / name
