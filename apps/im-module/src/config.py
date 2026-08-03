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
FEISHU_BITABLE_APP_TOKEN = os.environ.get("FEISHU_BITABLE_APP_TOKEN", "").strip()
FEISHU_BITABLE_TABLE_ID = os.environ.get("FEISHU_BITABLE_TABLE_ID", "").strip()
FEISHU_SYNC_COMMANDS = tuple(
    c.strip().lower()
    for c in (os.environ.get("FEISHU_SYNC_COMMANDS", "同步,sync") or "同步,sync").split(",")
    if c.strip()
)
SHEET_SEEN_FILE = Path(
    os.environ.get("SHEET_SEEN_FILE", str(_APP_ROOT / "state" / "sheet_seen.json"))
)
SHEET_SYNC_BATCH_SIZE = int(os.environ.get("SHEET_SYNC_BATCH_SIZE", "50") or "50")

# DingTalk: Client ID = AppKey, Client Secret = AppSecret; robotCode defaults to AppKey.
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
BUF_DONE_DIR = Path(os.environ.get("BUF_DONE_DIR", str(_AUTO / "buf_done")))
QUEUE_STATUS_FILE = Path(
    os.environ.get("QUEUE_STATUS_FILE", str(_AUTO / "state" / "queue_status.json"))
)

POLL_SEC = float(os.environ.get("POLL_SEC", "3") or "3")
ZIP_WAIT_SEC = float(os.environ.get("ZIP_WAIT_SEC", "600") or "600")

OPS_TEMPLATE = (
    "用法：\n"
    "1) @机器人 同步  —— 从多维表格拉取新增下载地址入队\n"
    "2) @机器人 后跟 JSON\n"
    '{"get-texts":{"urls":["https://example.com/game.apk"]}}'
)
