from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionTarget:
    kind: str  # group | oto
    value: str

    def to_key(self) -> str:
        return f"{self.kind}:{self.value}"


def session_from_incoming(
    *,
    conversation_type: str | None,
    conversation_id: str | None,
    sender_staff_id: str | None,
) -> SessionTarget | None:
    ctype = str(conversation_type or "")
    if ctype == "2":
        cid = (conversation_id or "").strip()
        if not cid:
            return None
        return SessionTarget(kind="group", value=cid)
    if ctype == "1":
        uid = (sender_staff_id or "").strip()
        if not uid:
            return None
        return SessionTarget(kind="oto", value=uid)
    return None


def parse_session_key(chat_id: str) -> SessionTarget:
    raw = (chat_id or "").strip()
    if raw.startswith("group:"):
        return SessionTarget(kind="group", value=raw[len("group:") :])
    if raw.startswith("oto:"):
        return SessionTarget(kind="oto", value=raw[len("oto:") :])
    # Backward / manual: bare id treated as group openConversationId.
    if not raw:
        raise ValueError("empty dingtalk session key")
    return SessionTarget(kind="group", value=raw)
