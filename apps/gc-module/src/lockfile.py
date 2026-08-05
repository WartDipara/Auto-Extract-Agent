from __future__ import annotations

import logging
import os
from pathlib import Path

import config
from audit import ensure_state_dir

_log = logging.getLogger(__name__)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except AttributeError:
        # Windows: os.kill exists in modern Python; fallback OpenProcess via ctypes if needed.
        return False
    return True


def acquire_lock(path: Path | None = None) -> bool:
    """Return True if this process owns the lock."""
    ensure_state_dir()
    lock = Path(path or config.LOCK_PATH)
    my_pid = os.getpid()
    if lock.is_file():
        try:
            old = int((lock.read_text(encoding="utf-8") or "").strip() or "0")
        except ValueError:
            old = 0
        if old and old != my_pid and _pid_alive(old):
            _log.error("another gc-module holds lock pid=%s path=%s", old, lock)
            return False
        _log.warning("stale gc.lock pid=%s; taking over", old)
    lock.write_text(str(my_pid), encoding="utf-8")
    return True


def release_lock(path: Path | None = None) -> None:
    lock = Path(path or config.LOCK_PATH)
    if not lock.is_file():
        return
    try:
        old = int((lock.read_text(encoding="utf-8") or "").strip() or "0")
    except ValueError:
        old = 0
    if old in (0, os.getpid()):
        try:
            lock.unlink()
        except OSError:
            pass
