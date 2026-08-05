from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import config


def parse_utc(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_aged(raw: str, *, retention_sec: float | None = None, now: float | None = None) -> bool:
    """True when timestamp is parseable and at least retention_sec old."""
    dt = parse_utc(raw)
    if dt is None:
        return False
    limit = config.RETENTION_SEC if retention_sec is None else retention_sec
    import time

    current = time.time() if now is None else now
    return (current - dt.timestamp()) >= limit


def row_eligible(
    row: dict[str, Any],
    *,
    retention_sec: float | None = None,
    now: float | None = None,
) -> tuple[bool, str]:
    """
    Return (ok, reason).

    ok reasons: delivered | no_im_chat
    reject reasons: not_terminal | active | delivered_too_young |
                    awaiting_im_delivery | no_im_chat_too_young |
                    timestamp_unparseable
    """
    status = str(row.get("status") or "").strip()
    if status in config.ACTIVE_STATUSES:
        return False, "active"
    if status not in config.TERMINAL_STATUSES:
        return False, "not_terminal"

    chat = str(row.get("im_chat_id") or "").strip()
    delivered = str(row.get("im_delivered_at") or "").strip()
    finished = str(row.get("finished_at") or "").strip()
    limit = config.RETENTION_SEC if retention_sec is None else retention_sec

    if delivered:
        if parse_utc(delivered) is None:
            return False, "timestamp_unparseable"
        if is_aged(delivered, retention_sec=limit, now=now):
            return True, "delivered"
        return False, "delivered_too_young"

    if chat:
        return False, "awaiting_im_delivery"

    if not finished:
        return False, "no_im_chat_too_young"
    if parse_utc(finished) is None:
        return False, "timestamp_unparseable"
    if is_aged(finished, retention_sec=limit, now=now):
        return True, "no_im_chat"
    return False, "no_im_chat_too_young"
