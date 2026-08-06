from __future__ import annotations

import json
import logging
import threading
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from time import monotonic
from typing import Callable

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateFileRequest,
    CreateFileRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
    EventMessage,
    EventSender,
)

from channels.base import IncomingChat, MessageHandler

_log = logging.getLogger(__name__)


class _SeenIds:
    """TTL-bounded dedup cache keyed by message_id (Feishu may re-push events)."""

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


# Trigger rules: a message is handled only when every rule passes.
# Adding a future rule = append one function here; _dispatch never changes.
_TRIGGER_RULES: list[Callable[[EventMessage, EventSender], bool]] = []


def _register_rule(
    fn: Callable[[EventMessage, EventSender], bool],
) -> Callable[[EventMessage, EventSender], bool]:
    _TRIGGER_RULES.append(fn)
    return fn


@_register_rule
def _rule_user_sender(msg: EventMessage, sender: EventSender) -> bool:
    """Only users may trigger the bot (blocks bot-to-bot loops)."""
    return sender.sender_type == "user"


@_register_rule
def _rule_mention_or_p2p(msg: EventMessage, sender: EventSender) -> bool:
    """p2p direct chats pass; group chats require a bot mention."""
    if msg.chat_type == "p2p":
        return True
    if msg.chat_type != "group":
        return False
    return any(m.mentioned_type == "bot" for m in (msg.mentions or []))


class FeishuChannel:
    def __init__(self, app_id: str, app_secret: str):
        self._app_id = app_id
        self._app_secret = app_secret
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )
        self._on_message: MessageHandler | None = None
        self._seen = _SeenIds()
        self._stop = threading.Event()

    def start(self, on_message: MessageHandler) -> None:
        self._on_message = on_message
        self._stop.clear()

        # Official: builder("", "") for long connection (no encrypt/token).
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._dispatch)
            .build()
        )
        reconnect_sec = 3.0
        try:
            import config as _cfg

            reconnect_sec = float(getattr(_cfg, "FEISHU_RECONNECT_SEC", 3.0))
        except Exception:
            reconnect_sec = 3.0

        _log.info("feishu websocket starting")
        while not self._stop.is_set():
            cli = lark.ws.Client(
                self._app_id,
                self._app_secret,
                event_handler=event_handler,
                log_level=lark.LogLevel.INFO,
            )
            try:
                cli.start()
            except KeyboardInterrupt:
                break
            except Exception:
                _log.exception("feishu websocket failed")
            if self._stop.is_set():
                break
            _log.warning(
                "feishu websocket disconnected; retry in %ss", reconnect_sec
            )
            if self._stop.wait(reconnect_sec):
                break
        _log.info("feishu websocket stopped")

    def stop(self) -> None:
        self._stop.set()

    def _dispatch(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        try:
            event = data.event
            if event is None or event.message is None or event.sender is None:
                return
            if self._seen.is_duplicate(event.message.message_id):
                return
            if not all(rule(event.message, event.sender) for rule in _TRIGGER_RULES):
                return
            chat_id, text = _parse_receive(data)
            if not chat_id or text is None:
                return
            sender_id = ""
            try:
                sender_id = str(
                    getattr(getattr(event.sender, "sender_id", None), "user_id", "")
                    or ""
                ).strip()
            except Exception:
                sender_id = ""
            if self._on_message:
                self._on_message(
                    IncomingChat(
                        chat_id=chat_id,
                        text=text,
                        sender_id=sender_id,
                    )
                )
        except Exception:
            _log.exception("feishu message handler failed")

    def reply_text(
        self,
        chat_id: str,
        text: str,
        *,
        at_user_ids: Sequence[str] | None = None,
    ) -> None:
        _ = at_user_ids
        body = CreateMessageRequestBody.builder().receive_id(chat_id).msg_type(
            "text"
        ).content(json.dumps({"text": text}, ensure_ascii=False)).build()
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        resp = self._client.im.v1.message.create(req)
        if not resp.success():
            _log.error("reply_text failed code=%s msg=%s", resp.code, resp.msg)
            raise RuntimeError(
                f"feishu reply_text failed code={resp.code} msg={resp.msg}"
            )

    def send_file(self, chat_id: str, path: Path) -> None:
        path = Path(path)
        with path.open("rb") as fp:
            file_req = (
                CreateFileRequest.builder()
                .request_body(
                    CreateFileRequestBody.builder()
                    .file_type("stream")
                    .file_name(path.name)
                    .file(fp)
                    .build()
                )
                .build()
            )
            file_resp = self._client.im.v1.file.create(file_req)
        if not file_resp.success() or not file_resp.data:
            _log.error("upload failed code=%s msg=%s", file_resp.code, file_resp.msg)
            raise RuntimeError(f"feishu upload failed: {file_resp.msg}")
        file_key = file_resp.data.file_key
        msg_body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("file")
            .content(json.dumps({"file_key": file_key}))
            .build()
        )
        msg_req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(msg_body)
            .build()
        )
        msg_resp = self._client.im.v1.message.create(msg_req)
        if not msg_resp.success():
            _log.error("send_file failed code=%s msg=%s", msg_resp.code, msg_resp.msg)
            raise RuntimeError(f"feishu send_file failed: {msg_resp.msg}")


def _parse_receive(data: lark.im.v1.P2ImMessageReceiveV1) -> tuple[str, str | None]:
    event = data.event
    if event is None or event.message is None:
        return "", None
    msg = event.message
    chat_id = msg.chat_id or ""
    if msg.message_type != "text" or not msg.content:
        return chat_id, None
    try:
        content = json.loads(msg.content)
    except json.JSONDecodeError:
        return chat_id, None
    text = content.get("text")
    if not isinstance(text, str):
        return chat_id, None
    # Strip @mention tokens like @_user_1
    cleaned = " ".join(part for part in text.split() if not part.startswith("@_"))
    return chat_id, cleaned.strip()
