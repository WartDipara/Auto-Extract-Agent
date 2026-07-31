"""IM module settings from environment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_APP_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _APP_ROOT.parent.parent
_AUTO = _REPO_ROOT / "apps" / "auto-extract"

load_dotenv(_APP_ROOT / ".env")

# feishu | dingtalk (aliases: lark | dingding)
IM_CHANNEL = os.environ.get("IM_CHANNEL", "feishu").strip().lower() or "feishu"

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "").strip()
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "").strip()

INBOX_DIR = Path(os.environ.get("INBOX_DIR", str(_AUTO / "inbox")))
BUF_DONE_DIR = Path(os.environ.get("BUF_DONE_DIR", str(_AUTO / "buf_done")))
QUEUE_STATUS_FILE = Path(
    os.environ.get("QUEUE_STATUS_FILE", str(_AUTO / "state" / "queue_status.json"))
)

POLL_SEC = float(os.environ.get("POLL_SEC", "3") or "3")
ZIP_WAIT_SEC = float(os.environ.get("ZIP_WAIT_SEC", "600") or "600")

OPS_TEMPLATE = (
    '格式：@机器人 后跟 JSON\n'
    '{"get-texts":{"urls":["https://example.com/game.apk"]}}'
)
