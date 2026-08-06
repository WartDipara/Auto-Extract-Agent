from __future__ import annotations

from pathlib import Path

from shared.module_registry import SHARED_TASKS_DB, all_modules, primary_module

_APP_ROOT = Path(__file__).resolve().parent.parent

MODULES = list(all_modules())
_PRIMARY = primary_module()

WORKSPACE_ROOT = _PRIMARY.workspace_root
DOWNLOADS_DIR = _PRIMARY.downloads_dir
RESULT_DIR = _PRIMARY.result_dir
BUF_DONE_DIR = _PRIMARY.buf_done_dir
TASKS_DB = SHARED_TASKS_DB
TASKS_TABLE = _PRIMARY.tasks_table

STATE_DIR = (_APP_ROOT / "state").resolve()
LOCK_PATH = STATE_DIR / "gc.lock"
AUDIT_PATH = STATE_DIR / "gc_audit.jsonl"
SERVICE_LOG = STATE_DIR / "service.log"

RETENTION_DAYS = 7.0
RETENTION_SEC = RETENTION_DAYS * 86400.0
INTERVAL_SEC = 3600.0
DRY_RUN_ENV = False

TERMINAL_STATUSES = _PRIMARY.terminal_statuses
ACTIVE_STATUSES = _PRIMARY.active_statuses
