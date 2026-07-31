"""Feishu long-connection channel via official lark-oapi (see open.feishu.cn)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateFileRequest,
    CreateFileRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
)

from channels.base import MessageHandler

_log = logging.getLogger(__name__)


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

    def start(self, on_message: MessageHandler) -> None:
        self._on_message = on_message

        def _handle(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
            try:
                chat_id, text = _parse_receive(data)
                if not chat_id or text is None:
                    return
                if self._on_message:
                    self._on_message(chat_id, text)
            except Exception:
                _log.exception("feishu message handler failed")

        # Official: builder("", "") for long connection (no encrypt/token).
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(_handle)
            .build()
        )
        cli = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )
        _log.info("feishu websocket starting")
        cli.start()

    def reply_text(self, chat_id: str, text: str) -> None:
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
