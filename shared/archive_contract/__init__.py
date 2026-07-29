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
import os
import re
import shutil
import stat
import subprocess
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

_WIN_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
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


def sanitize_label_for_filename(label: str) -> str:
    text = (label or "").strip()
    if not text:
        return "unknown"
    text = _WIN_BAD.sub("_", text)
    text = text.replace(" ", "")
    text = re.sub(r"_+", "_", text).strip("._")
    if len(text) > 80:
        text = text[:80].rstrip("._")
    return text or "unknown"


def clean_result_csv(text: str) -> tuple[str, str]:
    """Strip optional `text` header and `__SESSION_ID__:` footer. Returns (body, session_id)."""
    lines = text.splitlines()
    session_id = ""
    if lines and lines[0].strip() == "text":
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("__SESSION_ID__:"):
        session_id = lines[-1].split(":", 1)[1].strip()
        lines = lines[:-1]
    body = "\n".join(lines).strip("\n")
    if body:
        body = body + "\n"
    return body, session_id


def default_result_csv_path(result_dir: Path, task_key: str, label: str) -> Path:
    safe = sanitize_label_for_filename(label)
    return Path(result_dir) / f"{task_key}_{safe}.csv"


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
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "rmdir", "/s", "/q", str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if not path.exists():
                return
        time.sleep(0.3)
    if path.exists():
        _log.warning("rmtree_force incomplete: %s", path)


def has_module_a_done(task_root: Path) -> bool:
    return (Path(task_root) / MODULE_A_DONE).is_file()


def has_followup_lock(task_root: Path) -> bool:
    return (Path(task_root) / FOLLOWUP_LOCK).is_file()


def has_stop(task_root: Path) -> bool:
    return (Path(task_root) / STOP_MARKER).is_file()


def mark_module_a_done(task_root: Path) -> None:
    (Path(task_root) / MODULE_A_DONE).write_text("", encoding="utf-8")


def mark_stop(task_root: Path) -> Path:
    path = Path(task_root) / STOP_MARKER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def purge_stopped_workspaces(workspace_root: Path) -> list[str]:
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
    if has_stop(root):
        raise RuntimeError(f"task stopped: {root.name}")
    if not has_module_a_done(root):
        raise RuntimeError(f"module A not done: {root.name}")
    lock = root / FOLLOWUP_LOCK
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"followup already running: {root.name}") from exc
    try:
        os.write(fd, b"")
    finally:
        os.close(fd)


def release_followup_lock(task_root: Path) -> None:
    lock = Path(task_root) / FOLLOWUP_LOCK
    if lock.is_file():
        lock.unlink()


def reset_task_workspace(workspace_root: Path, task_key: str) -> Path:
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
