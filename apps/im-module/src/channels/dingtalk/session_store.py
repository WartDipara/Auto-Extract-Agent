from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from channels.dingtalk.openapi import SessionReplyTarget

_log = logging.getLogger(__name__)


def load_session_replies(path: Path) -> dict[str, SessionReplyTarget]:
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _log.exception("dingtalk session store read failed path=%s", path)
        return {}
    if not isinstance(raw, dict):
        return {}
    now_ms = int(time.time() * 1000)
    out: dict[str, SessionReplyTarget] = {}
    for chat_id, item in raw.items():
        if not isinstance(chat_id, str) or not isinstance(item, dict):
            continue
        webhook = str(item.get("webhook") or "").strip()
        try:
            expire_at = int(item.get("expire_at_ms") or 0)
        except (TypeError, ValueError):
            continue
        target = SessionReplyTarget(
            webhook=webhook,
            expire_at_ms=expire_at,
            sender_staff_id=str(item.get("sender_staff_id") or "").strip(),
            sender_nick=str(item.get("sender_nick") or "").strip(),
        )
        if not target.alive(now_ms=now_ms):
            continue
        out[chat_id] = target
    return out


def save_session_replies(path: Path, replies: dict[str, SessionReplyTarget]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now_ms = int(time.time() * 1000)
    payload: dict[str, dict[str, object]] = {}
    for chat_id, target in replies.items():
        if not target.alive(now_ms=now_ms):
            continue
        payload[chat_id] = {
            "webhook": target.webhook,
            "expire_at_ms": target.expire_at_ms,
            "sender_staff_id": target.sender_staff_id,
            "sender_nick": target.sender_nick,
        }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
