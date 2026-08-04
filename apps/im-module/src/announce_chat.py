from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

_log = logging.getLogger(__name__)
_lock = threading.Lock()


def load_learned_chat(path: Path) -> str:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("chat_id") or "").strip()


def save_learned_chat(path: Path, chat_id: str) -> bool:
    """Persist last active chat. Returns True if value changed."""
    cid = (chat_id or "").strip()
    if not cid:
        return False
    target = Path(path)
    with _lock:
        prev = load_learned_chat(target)
        if prev == cid:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"chat_id": cid}
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(target)
        _log.info("announce chat learned: %s (was %s)", cid, prev or "-")
        return True


def resolve_announce_chat(*, pinned: str, state_path: Path) -> str:
    pin = (pinned or "").strip()
    if pin:
        return pin
    return load_learned_chat(state_path)
