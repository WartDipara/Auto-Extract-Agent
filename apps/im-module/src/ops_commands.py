from __future__ import annotations

import re
from dataclasses import dataclass

LEDGER_STATUSES = frozenset(
    {
        "queued",
        "downloaded",
        "patched",
        "on_device",
        "device_done",
        "on_extract",
        "extract_done",
        "success",
        "decrypt_failed",
        "assets_missing",
        "abnormal_exit",
        "failed",
        "timeout",
    }
)

TERMINAL_STATUSES = frozenset(
    {
        "success",
        "decrypt_failed",
        "assets_missing",
        "abnormal_exit",
        "failed",
        "timeout",
    }
)

ACTIVE_STATUSES = frozenset(s for s in LEDGER_STATUSES if s not in TERMINAL_STATUSES)

_HELP_ALIASES = frozenset({"help", "?"})
_QUERY_HEAD = re.compile(r"^query(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class OpsCommand:
    kind: str
    arg: str = ""


def parse_ops_command(text: str) -> OpsCommand | None:
    raw = " ".join((text or "").strip().split())
    if not raw:
        return None
    lower = raw.lower()
    if lower in _HELP_ALIASES or lower == "query":
        return OpsCommand(kind="help")
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
    if mode == "export":
        return OpsCommand(kind="query_export")
    if mode == "password":
        return OpsCommand(kind="query_password")
    if mode == "gid":
        return OpsCommand(kind="query_gid", arg=tail)
    if mode == "status":
        return OpsCommand(kind="query_status", arg=tail)
    return OpsCommand(kind="help")


def is_valid_ledger_status(status: str) -> bool:
    return (status or "").strip() in LEDGER_STATUSES
