from __future__ import annotations

import os
import random
from pathlib import Path

from dotenv import load_dotenv

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

INBOX_DIR = (_AUTO / "inbox").resolve()
TASKS_DB = (_AUTO / "state" / "tasks.db").resolve()
QUERY_EXPORT_DIR = (_APP_ROOT / "state" / "query_exports").resolve()
ZIP_PASSWORD = (os.environ.get("ZIP_PASSWORD") or "").strip()

POLL_SEC = 3.0
ZIP_WAIT_SEC = 600.0

_announce = (os.environ.get("ANNOUNCE_CHAT_ID") or "").strip()
if not _announce and IM_CHANNEL in ("dingtalk", "dingding"):
    _announce = (os.environ.get("DINGTALK_TEST_CHAT_ID") or "").strip()
ANNOUNCE_CHAT_ID = _announce
ANNOUNCE_CHAT_STATE = (_APP_ROOT / "state" / "announce_chat.json").resolve()

CORE_HEARTBEAT_PATH = (_AUTO / "state" / "heartbeat").resolve()
CORE_HEARTBEAT_STALE_SEC = 15.0

BOT_NAME = "Lino"

MSG_BOT_ONLINE_VARIANTS = (
    f"{BOT_NAME}已就位，可以开始工作了",
    f"{BOT_NAME}准备好了～随时接消息",
    f"报到！{BOT_NAME}在线，把链接丢过来就行",
    f"{BOT_NAME}上线了，有需要直接喊{BOT_NAME}",
    f"嗯，{BOT_NAME}来了。已就位！",
)
MSG_BOT_OFFLINE_VARIANTS = (
    f"{BOT_NAME}目前有急事，先去休息了",
    f"{BOT_NAME}去歇会儿，稍后再来～",
    f"先休息啦，有事稍后找{BOT_NAME}",
    f"{BOT_NAME}先去休息了，下次再一起合作",
    f"{BOT_NAME}家里的金鱼溺水了，先离开一下",
)
MSG_CORE_DOWN_VARIANTS = (
    f"出故障了：（ 等{BOT_NAME}去修修",
    f"后台卡住了，{BOT_NAME}去敲两下再来",
    f"哎呀服务罢工了，稍等{BOT_NAME}抢修",
    f"报错了，先别催单，{BOT_NAME}去处理",
    "出了点状况……修完马上回来",
)
MSG_CORE_UP_VARIANTS = (
    "搞定了，又可以正常工作了",
    "修好啦，可以继续干活了",
    "恢复正常，可以继续了",
    "抢修完成，继续开工！",
    "活过来了～服务已恢复",
)

OPS_TEMPLATE = (
    "用法：\n"
    "【提交任务】直接填入 APK 下载链接，可多条\n"
    "  @艺术家 https://example.com/a.apk\n"
    "  @艺术家 https://example.com/b.apk\n"
    "  ......\n"
    "\n"
    "【查询】\n"
    "  @艺术家 query progress          查询进行中的任务\n"
    "  @艺术家 query status success    按状态筛选（如 success / failed / timeout）\n"
    "  @艺术家 query gid t-0002        查单个任务\n"
    "  @艺术家 query export            导出全表 Excel\n"
    "  @艺术家 query password          查看 .bin 解压密码\n"
    "\n"
    "【帮助】help / ?    【打招呼】你好 / hi\n"
    "\n"
    "【你会收到什么】\n"
    "  成功：群里回传一个 .bin 文件（本质是加密 zip，改后缀）\n"
    "        里面是提取出的文本 CSV；用 zip 工具 + 密码解压即可\n"
    "  失败：群里直接发文字说明（状态 + 原因）\n"
    "\n"
    "【任务时长预期】 15-50 分钟，最大不超过二小时\n"
    "【解压密码】\n"
    "  仅用于打开成功回传的 .bin（当 zip 解压）；\n"
    "  防止文件在传输时被平台误扫。忘记了就用 query password 查询。"
)

_MSG_GREET_BODIES = (
    (
        f"你好，我是{BOT_NAME}～\n"
        f"{BOT_NAME}负责传话：你把 APK 下载链接发给{BOT_NAME}，"
        f"{BOT_NAME}会转给专人帮你解决，完成后把结果发回给你。"
    ),
    (
        f"嗨，我是{BOT_NAME}。\n"
        f"{BOT_NAME}负责传信的：你给{BOT_NAME}链接，{BOT_NAME}帮忙登记排队，"
        "有结果了再送回群里。"
    ),
    (
        f"你好呀，{BOT_NAME}在此～\n"
        f"别跟{BOT_NAME}聊太复杂的，发下载链接就对了；"
        f"中间怎么处理不用操心，有消息{BOT_NAME}会告诉你。"
    ),
    (
        f"Hello，我是{BOT_NAME}！\n"
        f"你负责丢链接，{BOT_NAME}负责传话和回传结果。"
    ),
    (
        f"在的，我是{BOT_NAME}。\n"
        f"把下载地址发给{BOT_NAME}，"
        f"办完后{BOT_NAME}会把结果回传给你。"
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
