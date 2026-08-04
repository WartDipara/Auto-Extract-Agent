from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_APP_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _APP_ROOT.parent.parent
_AUTO = _REPO_ROOT / "apps" / "auto-extract"

load_dotenv(_APP_ROOT / ".env")

IM_CHANNEL = os.environ.get("IM_CHANNEL", "feishu").strip().lower() or "feishu"

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "").strip()
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "").strip()

DINGTALK_CLIENT_ID = (
    os.environ.get("DINGTALK_CLIENT_ID", "").strip()
    or os.environ.get("DINGTALK_APP_KEY", "").strip()
)
DINGTALK_CLIENT_SECRET = (
    os.environ.get("DINGTALK_CLIENT_SECRET", "").strip()
    or os.environ.get("DINGTALK_APP_SECRET", "").strip()
)
DINGTALK_ROBOT_CODE = os.environ.get("DINGTALK_ROBOT_CODE", "").strip()

INBOX_DIR = Path(os.environ.get("INBOX_DIR", str(_AUTO / "inbox")))
TASKS_DB = Path(os.environ.get("TASKS_DB", str(_AUTO / "state" / "tasks.db")))
QUERY_EXPORT_DIR = Path(
    os.environ.get("QUERY_EXPORT_DIR", str(_APP_ROOT / "state" / "query_exports"))
)

POLL_SEC = float(os.environ.get("POLL_SEC", "3") or "3")
ZIP_WAIT_SEC = float(os.environ.get("ZIP_WAIT_SEC", "600") or "600")

OPS_TEMPLATE = (
    "Usage:\n"
    "1) Query ledger (CSV file reply)\n"
    "   @bot query all\n"
    "   @bot query top_n 20\n"
    "   @bot query gid t-0002\n"
    "   @bot query status success\n"
    "2) Enqueue (paste APK URL(s), one per line or space-separated)\n"
    "   @bot https://example.com/game.apk"
)
