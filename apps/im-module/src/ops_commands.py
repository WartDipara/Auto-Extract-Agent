from __future__ import annotations

import re
from dataclasses import dataclass

from shared.module_registry import primary_module

_PRIMARY = primary_module()

LEDGER_STATUSES = frozenset(_PRIMARY.active_statuses | _PRIMARY.terminal_statuses)
TERMINAL_STATUSES = frozenset(_PRIMARY.terminal_statuses)
ACTIVE_STATUSES = frozenset(_PRIMARY.active_statuses)

# User-facing filters (export / query status). Fine DB statuses stay internal.
USER_STATUS_FILTERS = ("all", "running", "success", "failed")
_FAILED_STATUSES = frozenset(
    s for s in TERMINAL_STATUSES if s != "success"
)

# Single source for user-visible status text (chat + export).
STATUS_LABEL_ZH: dict[str, str] = {
    "queued": "排队中",
    "downloaded": "已下载",
    "patched": "已改包",
    "on_device": "设备处理中",
    "device_done": "设备完成",
    "on_extract": "提取中",
    "extract_done": "提取完成",
    "success": "成功",
    "decrypt_failed": "解密失败",
    "assets_missing": "资源缺失",
    "abnormal_exit": "异常退出",
    "failed": "失败",
    "timeout": "超时",
}

_FILTER_ALIASES: dict[str, str] = {
    "all": "all",
    "全部": "all",
    "running": "running",
    "progress": "running",
    "active": "running",
    "进行中": "running",
    "success": "success",
    "成功": "success",
    "failed": "failed",
    "fail": "failed",
    "error": "failed",
    "失败": "failed",
}


def status_label_zh(status: str) -> str:
    key = (status or "").strip()
    if not key:
        return "-"
    return STATUS_LABEL_ZH.get(key, key)


def resolve_status_filter(token: str) -> tuple[str, frozenset[str] | None] | None:
    """Map a user token to (display_label, status set). None set = no filter."""
    raw = (token or "").strip()
    if not raw:
        return None
    key = _FILTER_ALIASES.get(raw) or _FILTER_ALIASES.get(raw.lower())
    if key == "all":
        return ("全部", None)
    if key == "running":
        return ("进行中", ACTIVE_STATUSES)
    if key == "success":
        return ("成功", frozenset({"success"}))
    if key == "failed":
        return ("失败", _FAILED_STATUSES)
    # Legacy exact ledger status still accepted, not advertised in help.
    fine = raw.lower()
    if fine in LEDGER_STATUSES:
        return (status_label_zh(fine), frozenset({fine}))
    return None


def is_valid_ledger_status(status: str) -> bool:
    return resolve_status_filter(status) is not None


def user_status_help(*, include_all: bool = True) -> str:
    parts: list[str] = []
    if include_all:
        parts.append("all / 全部")
    parts.extend(
        [
            "running / 进行中",
            "success / 成功",
            "failed / 失败",
        ]
    )
    return " · ".join(parts)


_HELP_ALIASES = frozenset({"help", "?"})
_QUERY_HEAD = re.compile(r"^query(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_EXPORT_HEAD = re.compile(r"^export(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_PING_RE = re.compile(r"^ping[!！.。]*$", re.IGNORECASE)
_GREET_RE = re.compile(
    r"^(你好|您好|哈喽|嗨|在吗|在不在|早上好|下午好|晚上好|hi|hello|hey)"
    r"[呀啊哦呢嘛]*"
    r"[!！?？.。~～]*$",
    re.IGNORECASE,
)
_QUERY_MODES = frozenset({"progress", "mine", "password", "label", "status", "gid"})


@dataclass(frozen=True)
class OpsCommand:
    kind: str
    arg: str = ""


def parse_ops_command(text: str) -> OpsCommand | None:
    raw = " ".join((text or "").strip().split())
    if not raw:
        return None
    lower = raw.lower()
    if lower in _HELP_ALIASES or lower == "query" or lower == "export":
        return OpsCommand(kind="help")
    if _PING_RE.match(raw):
        return OpsCommand(kind="ping")
    if _GREET_RE.match(raw):
        return OpsCommand(kind="greet")

    export_m = _EXPORT_HEAD.match(raw)
    if export_m:
        rest = (export_m.group(1) or "").strip()
        if not rest:
            return OpsCommand(kind="help")
        parts = rest.split(None, 1)
        mode = parts[0].lower()
        tail = parts[1].strip() if len(parts) > 1 else ""
        # Only valid form: export table <range>
        if mode == "table":
            return OpsCommand(kind="export_table", arg=tail)
        # e.g. "export aaa" — recognized as export, but invalid shape.
        return OpsCommand(kind="export_usage")

    m = _QUERY_HEAD.match(raw)
    if not m:
        return None
    rest = (m.group(1) or "").strip()
    if not rest:
        return OpsCommand(kind="help")
    parts = rest.split(None, 1)
    mode = parts[0].lower()
    tail = parts[1].strip() if len(parts) > 1 else ""
    if mode == "progress":
        return OpsCommand(kind="query_progress")
    if mode == "mine":
        return OpsCommand(kind="query_mine")
    if mode == "password":
        return OpsCommand(kind="query_password")
    if mode == "gid":
        return OpsCommand(kind="query_gid", arg=tail)
    if mode == "label":
        return OpsCommand(kind="query_label", arg=tail)
    if mode == "status":
        return OpsCommand(kind="query_status", arg=tail)
    # e.g. "query export" — query has no export subcommand.
    if mode == "export" or mode not in _QUERY_MODES:
        if mode == "export":
            return OpsCommand(kind="export_usage")
        return OpsCommand(kind="query_usage")
    return OpsCommand(kind="help")
