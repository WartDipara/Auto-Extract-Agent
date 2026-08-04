from __future__ import annotations

import logging
import re
from collections import deque
from pathlib import Path
from time import monotonic
from typing import Callable

from dingtalk_stream import AckMessage, ChatbotMessage, Credential, DingTalkStreamClient
from dingtalk_stream.chatbot import ChatbotHandler

from channels.base import MessageHandler
from channels.dingtalk.openapi import DingTalkOpenApi
from channels.dingtalk.session import parse_session_key, session_from_incoming

_log = logging.getLogger(__name__)

# Strip leading @tokens DingTalk may leave in text.content after mention.
_AT_TOKEN_RE = re.compile(r"@\S+")


class _SeenIds:
    def __init__(self, ttl: float = 300, maxlen: int = 200):
        self._ttl = ttl
        self._maxlen = maxlen
        self._order: deque[tuple[float, str]] = deque()
        self._ids: set[str] = set()

    def is_duplicate(self, message_id: str | None) -> bool:
        if not message_id:
            return False
        now = monotonic()
        while self._order and self._order[0][0] < now - self._ttl:
            _, old = self._order.popleft()
            self._ids.discard(old)
        if message_id in self._ids:
            return True
        self._ids.add(message_id)
        self._order.append((now, message_id))
        while len(self._order) > self._maxlen:
            _, old = self._order.popleft()
            self._ids.discard(old)
        return False


_TRIGGER_RULES: list[Callable[[ChatbotMessage], bool]] = []


def _register_rule(
    fn: Callable[[ChatbotMessage], bool],
) -> Callable[[ChatbotMessage], bool]:
    _TRIGGER_RULES.append(fn)
    return fn


@_register_rule
def _rule_text_only(msg: ChatbotMessage) -> bool:
    return (msg.message_type or "") == "text"


@_register_rule
def _rule_mention_or_oto(msg: ChatbotMessage) -> bool:
    """1:1 always; group requires bot in at-list (DingTalk isInAtList)."""
    ctype = str(msg.conversation_type or "")
    if ctype == "1":
        return True
    if ctype == "2":
        return bool(msg.is_in_at_list)
    return False


class _StreamBotHandler(ChatbotHandler):
    def __init__(self, channel: DingTalkChannel):
        super().__init__()
        self._channel = channel

    async def process(self, callback):
        try:
            incoming = ChatbotMessage.from_dict(callback.data)
            self._channel.handle_incoming(incoming)
        except Exception:
            _log.exception("dingtalk stream handler failed")
        return AckMessage.STATUS_OK, "OK"


class DingTalkChannel:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        robot_code: str | None = None,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._robot_code = (robot_code or client_id).strip()
        self._api = DingTalkOpenApi(client_id, client_secret, self._robot_code)
        self._on_message: MessageHandler | None = None
        self._seen = _SeenIds()

    def start(self, on_message: MessageHandler) -> None:
        self._on_message = on_message
        credential = Credential(self._client_id, self._client_secret)
        client = DingTalkStreamClient(credential)
        client.register_callback_handler(
            ChatbotMessage.TOPIC,
            _StreamBotHandler(self),
        )
        _log.info(
            "dingtalk stream starting client_id=%s robot_code=%s topic=%s",
            self._client_id,
            self._robot_code,
            ChatbotMessage.TOPIC,
        )
        client.start_forever()

    def handle_incoming(self, msg: ChatbotMessage) -> None:
        if self._seen.is_duplicate(msg.message_id):
            return
        if not all(rule(msg) for rule in _TRIGGER_RULES):
            return
        target = session_from_incoming(
            conversation_type=msg.conversation_type,
            conversation_id=msg.conversation_id,
            sender_staff_id=msg.sender_staff_id,
        )
        if target is None:
            _log.warning(
                "dingtalk skip: cannot build session type=%s cid=%s staff=%s",
                msg.conversation_type,
                msg.conversation_id,
                msg.sender_staff_id,
            )
            return
        text = _extract_text(msg)
        if text is None:
            return
        if self._on_message:
            self._on_message(target.to_key(), text)

    def reply_text(self, chat_id: str, text: str) -> None:
        target = parse_session_key(chat_id)
        try:
            if target.kind == "group":
                self._api.send_group_text(target.value, text)
            elif target.kind == "oto":
                self._api.send_oto_text(target.value, text)
            else:
                raise ValueError(f"unknown session kind {target.kind}")
        except Exception:
            _log.exception("dingtalk reply_text failed chat_id=%s", chat_id)
            raise

    def send_file(self, chat_id: str, path: Path) -> None:
        # Enterprise robot OpenAPI has sampleText/Markdown/Image/Link templates;
        # arbitrary file/zip delivery is a separate media flow — not wired yet.
        raise NotImplementedError(
            "dingtalk send_file not implemented; use reply_text for now "
            f"(path={Path(path).name})"
        )


def _extract_text(msg: ChatbotMessage) -> str | None:
    if msg.text is None or msg.text.content is None:
        return None
    raw = str(msg.text.content)
    # Remove @mentions; keep the JSON / command body.
    cleaned = _AT_TOKEN_RE.sub(" ", raw)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned if cleaned else None
