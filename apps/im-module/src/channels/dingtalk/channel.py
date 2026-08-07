from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from collections import deque
from pathlib import Path
from time import monotonic
from typing import Callable, Sequence
from urllib.parse import quote_plus

import websockets
from dingtalk_stream import AckMessage, ChatbotMessage, Credential, DingTalkStreamClient
from dingtalk_stream.chatbot import ChatbotHandler

from channels.base import IncomingChat, MessageHandler
from channels.dingtalk.openapi import (
    DingTalkOpenApi,
    resolve_send_file_meta,
)
from channels.dingtalk.session import parse_session_key, session_from_incoming

_log = logging.getLogger(__name__)

_AT_TOKEN_RE = re.compile(r"@\S+")
_STREAM_POLL_SEC = 0.25


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
        self._stop = threading.Event()
        self._stream_client: DingTalkStreamClient | None = None
        self._stream_loop: asyncio.AbstractEventLoop | None = None

    def stop(self) -> None:
        self._stop.set()
        self._schedule_close_websocket()

    def _schedule_close_websocket(self) -> None:
        """Wake the blocked async-for by closing the active websocket."""
        loop = self._stream_loop
        client = self._stream_client
        if loop is None or client is None:
            return
        if not loop.is_running():
            return

        def _close() -> None:
            ws = getattr(client, "websocket", None)
            if ws is None:
                return
            try:
                asyncio.ensure_future(ws.close(), loop=loop)
            except Exception:
                _log.exception("dingtalk websocket close failed")

        try:
            loop.call_soon_threadsafe(_close)
        except Exception:
            _log.exception("dingtalk schedule websocket close failed")

    async def _sleep_unless_stopped(self, seconds: float) -> bool:
        """Sleep in slices; return True if stop was requested."""
        deadline = monotonic() + max(0.0, float(seconds))
        while not self._stop.is_set():
            remain = deadline - monotonic()
            if remain <= 0:
                return False
            await asyncio.sleep(min(_STREAM_POLL_SEC, remain))
        return True

    async def _stream_forever(self, client: DingTalkStreamClient) -> None:
        """
        Stoppable stream loop.

        Upstream DingTalkStreamClient.start() reconnects on CancelledError /
        ConnectionClosed and only exits on KeyboardInterrupt — so Ctrl+C via
        channel.stop() never unwound. Honor self._stop and close the socket.
        """
        self._stream_loop = asyncio.get_running_loop()
        self._stream_client = client
        client.pre_start()
        while not self._stop.is_set():
            try:
                connection = client.open_connection()
                if not connection:
                    _log.error("dingtalk open connection failed")
                    if await self._sleep_unless_stopped(10.0):
                        return
                    continue
                _log.info("dingtalk endpoint is %s", connection)
                uri = (
                    f'{connection["endpoint"]}'
                    f'?ticket={quote_plus(connection["ticket"])}'
                )
                async with websockets.connect(uri) as websocket:
                    client.websocket = websocket
                    keepalive = asyncio.create_task(client.keepalive(websocket))
                    try:
                        async for raw_message in websocket:
                            if self._stop.is_set():
                                return
                            json_message = json.loads(raw_message)
                            asyncio.create_task(
                                client.background_task(json_message)
                            )
                    finally:
                        keepalive.cancel()
                        try:
                            await keepalive
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            pass
                        client.websocket = None
            except KeyboardInterrupt:
                self._stop.set()
                return
            except (
                asyncio.CancelledError,
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
            ) as exc:
                if self._stop.is_set():
                    return
                _log.error("dingtalk network exception: %s", exc)
                if await self._sleep_unless_stopped(3.0):
                    return
            except Exception:
                if self._stop.is_set():
                    return
                _log.exception("dingtalk stream unknown exception")
                if await self._sleep_unless_stopped(3.0):
                    return

    def start(self, on_message: MessageHandler) -> None:
        self._on_message = on_message
        self._stop.clear()
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
        while not self._stop.is_set():
            try:
                asyncio.run(self._stream_forever(client))
            except KeyboardInterrupt:
                self._stop.set()
                break
            if self._stop.is_set():
                break
            _log.warning("dingtalk stream disconnected; retry in 3s")
            if self._stop.wait(3.0):
                break
        self._stream_loop = None
        self._stream_client = None
        _log.info("dingtalk stream stopped")

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
        chat_id = target.to_key()
        sender_id = (msg.sender_staff_id or "").strip()
        sender_name = (msg.sender_nick or "").strip()
        if self._on_message:
            self._on_message(
                IncomingChat(
                    chat_id=chat_id,
                    text=text,
                    sender_id=sender_id,
                    sender_name=sender_name,
                )
            )

    def reply_text(
        self,
        chat_id: str,
        text: str,
        *,
        at_user_ids: Sequence[str] | None = None,
    ) -> None:
        """Unified outbound: OpenAPI to the chat only (stay in the group)."""
        _ = at_user_ids  # Group OpenAPI cannot @; keep arg for Channel API parity.
        self._reply_openapi(chat_id, text)

    def broadcast_text(self, chat_id: str, text: str) -> None:
        """Lifecycle broadcast — same OpenAPI path."""
        self._reply_openapi(chat_id, text)

    def _reply_openapi(self, chat_id: str, text: str) -> None:
        target = parse_session_key(chat_id)
        try:
            if target.kind == "group":
                self._api.send_group_text(target.value, text)
                _log.info(
                    "dingtalk reply channel=openapi chat_id=%s",
                    chat_id,
                )
            elif target.kind == "oto":
                # Only used as last resort when the original group is gone.
                self._api.send_oto_text(target.value, text)
                _log.info("dingtalk reply channel=oto chat_id=%s", chat_id)
            else:
                raise ValueError(f"unknown session kind {target.kind}")
        except Exception:
            _log.exception("dingtalk reply_text failed chat_id=%s", chat_id)
            raise

    def send_file(self, chat_id: str, path: Path) -> None:
        path = Path(path)
        file_name, file_type = resolve_send_file_meta(path)
        target = parse_session_key(chat_id)
        try:
            media_id = self._api.upload_media(path, media_type="file")
            if target.kind == "group":
                self._api.send_group_file(
                    target.value,
                    media_id=media_id,
                    file_name=file_name,
                    file_type=file_type,
                )
            elif target.kind == "oto":
                self._api.send_oto_file(
                    target.value,
                    media_id=media_id,
                    file_name=file_name,
                    file_type=file_type,
                )
            else:
                raise ValueError(f"unknown session kind {target.kind}")
        except Exception:
            _log.exception(
                "dingtalk send_file failed chat_id=%s path=%s", chat_id, path.name
            )
            raise

    def outgoing_file_name(self, path: Path) -> str:
        # Legacy .bin packs still map to zip upload type for DingTalk.
        name, _ = resolve_send_file_meta(path)
        return name


def _extract_text(msg: ChatbotMessage) -> str | None:
    if msg.text is None or msg.text.content is None:
        return None
    raw = str(msg.text.content)
    cleaned = _AT_TOKEN_RE.sub(" ", raw)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned if cleaned else None

