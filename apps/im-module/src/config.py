from __future__ import annotations

import os
import random
from pathlib import Path

from dotenv import load_dotenv

from shared.module_registry import (
    SHARED_TASKS_DB,
    all_modules,
    primary_module,
)

_APP_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _APP_ROOT.parent.parent
_AUTO = _REPO_ROOT / "apps" / "auto-extract"

load_dotenv(_APP_ROOT / ".env")
load_dotenv(_AUTO / ".env", override=False)

IM_CHANNEL = (os.environ.get("IM_CHANNEL") or "").strip().lower()

FEISHU_APP_ID = (os.environ.get("FEISHU_APP_ID") or "").strip()
FEISHU_APP_SECRET = (os.environ.get("FEISHU_APP_SECRET") or "").strip()

DINGTALK_CLIENT_ID = (
    (os.environ.get("DINGTALK_CLIENT_ID") or "").strip()
    or (os.environ.get("DINGTALK_APP_KEY") or "").strip()
)
DINGTALK_CLIENT_SECRET = (
    (os.environ.get("DINGTALK_CLIENT_SECRET") or "").strip()
    or (os.environ.get("DINGTALK_APP_SECRET") or "").strip()
)
DINGTALK_ROBOT_CODE = (os.environ.get("DINGTALK_ROBOT_CODE") or "").strip()

MODULES = list(all_modules())
_PRIMARY = primary_module()
_LEDGER_STATUSES = tuple(
    sorted(_PRIMARY.active_statuses | _PRIMARY.terminal_statuses)
)
_LEDGER_STATUS_HELP = " / ".join(("all", *_LEDGER_STATUSES))

INBOX_DIR = _PRIMARY.inbox_dir
TASKS_DB = SHARED_TASKS_DB
TASKS_TABLE = _PRIMARY.tasks_table
INBOX_ROUTE = _PRIMARY.inbox_route
QUERY_EXPORT_DIR = (_APP_ROOT / "state" / "query_exports").resolve()
ZIP_PASSWORD = (os.environ.get("ZIP_PASSWORD") or "").strip()

POLL_SEC = 3.0
ZIP_WAIT_SEC = 600.0
DELIVER_MAX_ATTEMPTS = 10
FILE_SENT_STATE = (_APP_ROOT / "state" / "file_sent.json").resolve()
FEISHU_RECONNECT_SEC = 3.0

_announce = (os.environ.get("ANNOUNCE_CHAT_ID") or "").strip()
if not _announce and IM_CHANNEL in ("dingtalk", "dingding"):
    _announce = (os.environ.get("DINGTALK_TEST_CHAT_ID") or "").strip()
ANNOUNCE_CHAT_ID = _announce
ANNOUNCE_CHAT_STATE = (_APP_ROOT / "state" / "announce_chat.json").resolve()
DELIVERY_AUDIT_PATH = (_APP_ROOT / "state" / "delivery_audit.jsonl").resolve()
PENDING_INBOX_STATE = (_APP_ROOT / "state" / "pending_inbox.json").resolve()
SERVICE_LOG = (_APP_ROOT / "state" / "service.log").resolve()
PENDING_INBOX_RESUBMIT_MAX = 3
PENDING_INBOX_STALE_TOUCH_SEC = 30.0
CORE_HEARTBEAT_PATH = _PRIMARY.heartbeat_path
CORE_HEARTBEAT_STALE_SEC = 15.0
CORE_SUBMIT_STALE_SEC = 10.0

BOT_NAME = "Viola"

MSG_BOT_ONLINE_VARIANTS = (
    f"{BOT_NAME}已上线，可以接收任务。",
    f"{BOT_NAME}已就位，请直接提交链接。",
    f"{BOT_NAME}在线，任务通道已就绪。",
)
MSG_BOT_OFFLINE_VARIANTS = (
    f"{BOT_NAME}即将下线，暂不可接收新任务。",
    f"{BOT_NAME}已下线，请稍后再提交。",
)
MSG_CORE_DOWN_VARIANTS = (
    f"处理服务异常，{BOT_NAME}正在排查；已登记任务会在恢复后继续。",
    f"处理服务暂不可用，修复完成后将自动继续未完成任务。",
    f"处理服务中断，请稍候；恢复后无需重复提交已登记任务。",
)
MSG_CORE_UP_VARIANTS = (
    "处理服务已恢复，可以继续提交任务。",
    "处理服务已恢复，未完成任务将自动继续。",
    "处理服务已恢复，通道正常。",
)

MSG_ENQUEUE_CORE_DEFERRED_FIRST = (
    "处理服务暂不可用；任务已登记，恢复后将自动继续。"
)
MSG_ENQUEUE_CORE_DEFERRED_AGAIN = (
    "处理服务仍在恢复中；任务已登记，恢复后将自动继续。"
)
OPS_TEMPLATE = (
    "用法：\n"
    "【提交任务】直接发送 APK 下载链接，可多条\n"
    f"  @{BOT_NAME} https://example.com/a.apk\n"
    f"  @{BOT_NAME} https://example.com/b.apk\n"
    "  ......\n"
    "  说明：同一 APK 文件名会覆盖旧任务并重新跑（任务号不变）\n"
    "\n"
    "【查询】\n"
    f"  @{BOT_NAME} query mine              查询我提交的任务进度\n"
    f"  @{BOT_NAME} query progress          查询全部处理中的任务\n"
    f"  @{BOT_NAME} query status success    按状态筛选\n"
    f"  @{BOT_NAME} query gid t-0002        按任务号查询\n"
    f"  @{BOT_NAME} query label 三国杀      按游戏名查询\n"
    f"  @{BOT_NAME} query password          查看 .zip 解压密码\n"
    "\n"
    "【导出】\n"
    f"  @{BOT_NAME} export table all        导出任务表（全部状态）\n"
    f"  @{BOT_NAME} export table success    导出指定状态的任务表\n"
    f"  可选状态：{_LEDGER_STATUS_HELP}\n"
    "  字段：filename / label / status / error / updated_at / finished_at\n"
    "  说明：账本按 filename 唯一；同名提交会覆盖旧记录\n"
    "\n"
    "【帮助】help / ?    【打招呼】你好 / hi\n"
    "\n"
    "【回传说明】\n"
    "  成功：群内回传加密 .zip，内含提取文本 CSV；\n"
    "        用常见解压工具输入密码即可打开。\n"
    "  失败：群内文字说明状态与原因。\n"
    "\n"
    "【时长预期】通常 15–50 分钟，最长不超过 2 小时。\n"
    "\n"
    "【解压密码】仅用于打开成功回传的 .zip；\n"
    "  忘记可用 query password 查询。"
)

_MSG_GREET_BODIES = (
    (
        f"你好，我是{BOT_NAME}。\n"
        f"请发送 APK 下载链接；{BOT_NAME}负责登记、调度，并在完成后回传结果。"
    ),
    (
        f"你好，我是{BOT_NAME}。\n"
        f"提交链接即可入队；处理完成后结果会发回本群。"
    ),
    (
        f"你好，我是{BOT_NAME}。\n"
        f"当前支持提交任务与查询；详情见下方用法。"
    ),
)


def pick_bot_online() -> str:
    return random.choice(MSG_BOT_ONLINE_VARIANTS)


def pick_bot_offline() -> str:
    return random.choice(MSG_BOT_OFFLINE_VARIANTS)


def pick_core_down() -> str:
    return random.choice(MSG_CORE_DOWN_VARIANTS)


def pick_core_up() -> str:
    return random.choice(MSG_CORE_UP_VARIANTS)


def pick_greet() -> str:
    return f"{random.choice(_MSG_GREET_BODIES)}\n\n{OPS_TEMPLATE}"


# Backward-compatible aliases (first variant / composed greet).
MSG_BOT_ONLINE = MSG_BOT_ONLINE_VARIANTS[0]
MSG_BOT_OFFLINE = MSG_BOT_OFFLINE_VARIANTS[0]
MSG_CORE_DOWN = MSG_CORE_DOWN_VARIANTS[0]
MSG_CORE_UP = MSG_CORE_UP_VARIANTS[0]
MSG_GREET = f"{_MSG_GREET_BODIES[0]}\n\n{OPS_TEMPLATE}"
