from __future__ import annotations

from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _APP_ROOT.parent.parent
_AUTO = _REPO_ROOT / "apps" / "auto-extract"

WORKSPACE_ROOT = (_AUTO / "workspace").resolve()
DOWNLOADS_DIR = (_AUTO / "downloads").resolve()
RESULT_DIR = (_AUTO / "result").resolve()
BUF_DONE_DIR = (_AUTO / "buf_done").resolve()
TASKS_DB = (_AUTO / "state" / "tasks.db").resolve()

STATE_DIR = (_APP_ROOT / "state").resolve()
LOCK_PATH = STATE_DIR / "gc.lock"
AUDIT_PATH = STATE_DIR / "gc_audit.jsonl"
SERVICE_LOG = STATE_DIR / "service.log"

RETENTION_DAYS = 7.0
RETENTION_SEC = RETENTION_DAYS * 86400.0
INTERVAL_SEC = 3600.0
DRY_RUN_ENV = False

TERMINAL_STATUSES = frozenset(
    {
        "success",
        "decrypt_failed",
        "assets_missing",
        "abnormal_exit",
        "failed",
        "timeout",
    }
)
ACTIVE_STATUSES = frozenset(
    {
        "queued",
        "downloaded",
        "patched",
        "on_device",
        "device_done",
        "on_extract",
        "extract_done",
    }
)
