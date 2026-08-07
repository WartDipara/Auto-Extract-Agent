from __future__ import annotations

import re
from dataclasses import dataclass

from shared.module_registry import primary_module

_PRIMARY = primary_module()

LEDGER_STATUSES = frozenset(_PRIMARY.active_statuses | _PRIMARY.terminal_statuses)
TERMINAL_STATUSES = frozenset(_PRIMARY.terminal_statuses)
ACTIVE_STATUSES = frozenset(_PRIMARY.active_statuses)

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
        # Only valid form: export table <all|status>
        if mode == "table":
            return OpsCommand(kind="export_table", arg=tail.lower())
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


def is_valid_ledger_status(status: str) -> bool:
    return (status or "").strip() in LEDGER_STATUSES
