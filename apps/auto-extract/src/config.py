from __future__ import annotations

import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

APP_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_ROOT.parent.parent
PROJECT_ROOT = APP_ROOT

load_dotenv(APP_ROOT / ".env")

WORKSPACE_ROOT = APP_ROOT / "workspace"

INBOX_DIR = APP_ROOT / "inbox"
DOWNLOADS_DIR = APP_ROOT / "downloads"
RESULT_DIR = APP_ROOT / "result"
BUF_DONE_DIR = APP_ROOT / "buf_done"
LOGS_DIR = APP_ROOT / "logs"
STATE_DIR = APP_ROOT / "state"
PROCESSED_DIR = STATE_DIR / "processed"
SESSIONS_FILE = STATE_DIR / "sessions.jsonl"
OPENCODE_SESSIONS_FILE = STATE_DIR / "opencode_sessions.jsonl"
QUEUE_STATUS_FILE = STATE_DIR / "queue_status.json"
HEARTBEAT_FILE = STATE_DIR / "heartbeat"
TASKS_DB = STATE_DIR / "tasks.db"

QUEUE_RECENT_DONE_MAX = 50
DOWNLOAD_WORKERS = 3
PATCH_WORKERS = 2
OPENCODE_SLOTS = 1
DEVICE_WAIT_TIMEOUT_SEC = 3600.0
OPENCODE_WAIT_TIMEOUT_SEC = 7200.0

# Required for buf_done encrypted pack; set in apps/auto-extract/.env
ZIP_PASSWORD = (os.environ.get("ZIP_PASSWORD") or "").strip()

DEBUG_KEYSTORE = STATE_DIR / "debug.keystore"

PROMPTS_FILE = APP_ROOT / "config" / "prompts.json"
PREP_FOREGROUND_POLL_SEC = 1.5
PREP_CRASH_CONFIRM = 3
PREP_BACKGROUND_CONFIRM = 2

OPENCODE_CMD = "opencode"
OPENCODE_SKILL = "get-game-text-skill"
OPENCODE_VARIANT = "max"
OPENCODE_OUTPUT_NAME = "tests.csv"
OPENCODE_STALL_SEC = 1800
OPENCODE_MISSING_OUTPUT_MAX = 2
OPENCODE_QUALITY_RESUME_MAX = 2
OPENCODE_EMPTY_CLASSIFY_MAX = 1

AGENT_TIMEOUT_SEC = 3600
POLL_INTERVAL_SEC = 2.0
CSV_GRACE_SEC = 10.0
ASSETS_MISSING_TEXT = "资源文本文件在assets里找不到"
DECRYPT_FAIL_TEXT = "解密失败"
ABNORMAL_EXIT_TEXT = "异常退出"
CSV_MIN_LINES = 5000
CSV_GARBLE_MIN_LINES = 10
CSV_GARBLE_RATIO = 0.01
SENSITIVE_HIT_MIN = 5
CSV_LARGE_REVIEW_LINES = 300000

DOWNLOAD_CHUNK_SIZE = 1024 * 256
DOWNLOAD_TIMEOUT_SEC = 300
AAPT_PATH = ""
ADB_CMD = "adb"
PREP_GATE_TIMEOUT_SEC = 1200
PREP_OCR_POLL_SEC = 3.0
PREP_AGENT_INTERVAL_SEC = 3.0
# Optional pin; empty = adb auto-pick. Set in .env only.
ADB_SERIAL = (os.environ.get("ADB_SERIAL") or "").strip()


def task_workspace(task_key: str) -> Path:
    return WORKSPACE_ROOT / task_key


def ensure_dirs():
    for path in (
        INBOX_DIR,
        DOWNLOADS_DIR,
        RESULT_DIR,
        BUF_DONE_DIR,
        LOGS_DIR,
        STATE_DIR,
        PROCESSED_DIR,
        WORKSPACE_ROOT,
    ):
        path.mkdir(parents=True, exist_ok=True)


def assert_extract_agent_ready():
    if not shutil.which(OPENCODE_CMD):
        raise RuntimeError(f"opencode not found in PATH ({OPENCODE_CMD!r})")
