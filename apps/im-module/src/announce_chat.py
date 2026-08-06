from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

_log = logging.getLogger(__name__)
_lock = threading.Lock()


def _normalize_chat_ids(raw) -> list[str]:
    if isinstance(raw, str):
        cid = raw.strip()
        return [cid] if cid else []
    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            cid = str(item or "").strip()
            if not cid or cid in seen:
                continue
            seen.add(cid)
            out.append(cid)
        return out
    return []


def load_learned_chats(path: Path) -> list[str]:
    """Load announce chat list. Backward compatible with {"chat_id": "..."}."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    if "chat_ids" in data:
        return _normalize_chat_ids(data.get("chat_ids"))
    return _normalize_chat_ids(data.get("chat_id"))


def load_learned_chat(path: Path) -> str:
    """First learned chat (compat for older callers)."""
    chats = load_learned_chats(path)
    return chats[0] if chats else ""


def add_announce_chat(path: Path, chat_id: str) -> bool:
    """Add chat to broadcast set. Returns True if newly added."""
    cid = (chat_id or "").strip()
    if not cid:
        return False
    target = Path(path)
    with _lock:
        chats = load_learned_chats(target)
        if cid in chats:
            return False
        chats.append(cid)
        _write_chats_unlocked(target, chats)
        _log.info("announce chat added: %s (n=%s)", cid, len(chats))
        return True


def remove_announce_chat(path: Path, chat_id: str) -> bool:
    """Drop a learned chat (dissolved group / robot left). Returns True if removed."""
    cid = (chat_id or "").strip()
    if not cid:
        return False
    target = Path(path)
    with _lock:
        chats = load_learned_chats(target)
        if cid not in chats:
            return False
        chats = [c for c in chats if c != cid]
        _write_chats_unlocked(target, chats)
        _log.warning("announce chat removed: %s (n=%s)", cid, len(chats))
        return True


def _write_chats_unlocked(target: Path, chats: list[str]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"chat_ids": chats}
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(target)


def save_learned_chat(path: Path, chat_id: str) -> bool:
    """Alias: add chat to the multi-group announce set."""
    return add_announce_chat(path, chat_id)


def parse_pinned_chats(pinned: str) -> list[str]:
    """ANNOUNCE_CHAT_ID may be one id or comma-separated list."""
    raw = (pinned or "").strip()
    if not raw:
        return []
    return _normalize_chat_ids([p.strip() for p in raw.split(",")])


def resolve_announce_chats(*, pinned: str, state_path: Path) -> list[str]:
    """Union of pinned chats and learned chats (order: pin first, then learned)."""
    out: list[str] = []
    seen: set[str] = set()
    for cid in (*parse_pinned_chats(pinned), *load_learned_chats(state_path)):
        if cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


def resolve_announce_chat(*, pinned: str, state_path: Path) -> str:
    """First announce target (compat). Prefer multi via resolve_announce_chats."""
    chats = resolve_announce_chats(pinned=pinned, state_path=state_path)
    return chats[0] if chats else ""
