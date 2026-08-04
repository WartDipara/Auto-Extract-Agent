from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_APP_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _APP_ROOT.parent.parent
_AUTO = _REPO_ROOT / "apps" / "auto-extract"

load_dotenv(_APP_ROOT / ".env")
# Shared Module A secrets (e.g. ZIP_PASSWORD); do not override IM vars.
load_dotenv(_AUTO / ".env", override=False)

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
ZIP_PASSWORD = (os.environ.get("ZIP_PASSWORD") or "").strip()

POLL_SEC = float(os.environ.get("POLL_SEC", "3") or "3")
ZIP_WAIT_SEC = float(os.environ.get("ZIP_WAIT_SEC", "600") or "600")

_announce = (os.environ.get("ANNOUNCE_CHAT_ID") or "").strip()
if not _announce and IM_CHANNEL in ("dingtalk", "dingding"):
    _announce = (os.environ.get("DINGTALK_TEST_CHAT_ID") or "").strip()
ANNOUNCE_CHAT_ID = _announce

CORE_HEARTBEAT_PATH = Path(
    os.environ.get(
        "CORE_HEARTBEAT_PATH",
        str(_AUTO / "state" / "heartbeat"),
    )
)
CORE_HEARTBEAT_STALE_SEC = float(
    os.environ.get("CORE_HEARTBEAT_STALE_SEC", "45") or "45"
)

MSG_BOT_ONLINE = "该上班力，画架支好——开工！"
MSG_BOT_OFFLINE = "下班咯，画室暂时打烊～"
MSG_CORE_DOWN = "画笔坏了:( 等我去买根新的再来！"
MSG_CORE_UP = "来了噢，开工！"

OPS_TEMPLATE = (
    "Usage:\n"
    "1) Query ledger\n"
    "   @bot query progress\n"
    "   @bot query status success\n"
    "   @bot query gid t-0002\n"
    "   @bot query export\n"
    "   @bot query password\n"
    "2) Enqueue (paste APK URL(s))\n"
    "   @bot https://example.com/game.apk"
)
