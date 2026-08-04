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

# Optional pin. Empty → auto-learn last active chat into ANNOUNCE_CHAT_STATE.
_announce = (os.environ.get("ANNOUNCE_CHAT_ID") or "").strip()
if not _announce and IM_CHANNEL in ("dingtalk", "dingding"):
    _announce = (os.environ.get("DINGTALK_TEST_CHAT_ID") or "").strip()
ANNOUNCE_CHAT_ID = _announce
ANNOUNCE_CHAT_STATE = Path(
    os.environ.get(
        "ANNOUNCE_CHAT_STATE",
        str(_APP_ROOT / "state" / "announce_chat.json"),
    )
)

CORE_HEARTBEAT_PATH = Path(
    os.environ.get(
        "CORE_HEARTBEAT_PATH",
        str(_AUTO / "state" / "heartbeat"),
    )
)
CORE_HEARTBEAT_STALE_SEC = float(
    os.environ.get("CORE_HEARTBEAT_STALE_SEC", "45") or "45"
)

MSG_BOT_ONLINE = "Lino已就位，可以开始工作了"
MSG_BOT_OFFLINE = "Lino目前有事，先走开了"
MSG_CORE_DOWN = "出故障了，等我去修修再来！"
MSG_CORE_UP = "搞定了，又可以正常运作力"

OPS_TEMPLATE = (
    "用法：\n"
    "\n"
    "【提交任务】直接填入APK的下载链接，可多条\n"
    "  @bot https://example.com/a.apk\n"
    "\n"
    "【查询】\n"
    "  query progress          查询进行中的任务\n"
    "  query status success    按状态筛选（如 success / failed / timeout）\n"
    "  query gid t-000       查单个任务\n"
    "  query export           导出全表 Excel\n"
    "  query password         查看一下解压密码\n"
    "\n"
    "【帮助】help  或  ?"
)
