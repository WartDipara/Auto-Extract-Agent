from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]
_IM_SRC = _ROOT / "apps" / "im-module" / "src"
for p in (_IM_SRC, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from channels.base import IncomingChat
from channels.dingtalk.channel import DingTalkChannel, _extract_text


def test_extract_text_strips_at_tokens():
    msg = MagicMock()
    msg.text = MagicMock()
    msg.text.content = "@机器人 query progress"
    assert _extract_text(msg) == "query progress"


def test_handle_incoming_records_sender_and_dispatches():
    channel = DingTalkChannel("cid", "secret", robot_code="bot")
    seen: list[IncomingChat] = []
    channel._on_message = seen.append

    msg = MagicMock()
    msg.message_id = "m1"
    msg.message_type = "text"
    msg.conversation_type = "2"
    msg.conversation_id = "cid-abc"
    msg.is_in_at_list = True
    msg.sender_staff_id = "staff-9"
    msg.sender_nick = "Bob"
    msg.text = MagicMock()
    msg.text.content = "@bot query gid t-0001"

    channel.handle_incoming(msg)
    assert len(seen) == 1
    assert seen[0].chat_id == "group:cid-abc"
    assert seen[0].text == "query gid t-0001"
    assert seen[0].sender_id == "staff-9"
    assert seen[0].sender_name == "Bob"


def test_reply_text_stays_in_group_no_oto(monkeypatch):
    channel = DingTalkChannel("cid", "secret", robot_code="bot")
    groups: list[tuple[str, str]] = []
    otos: list = []

    monkeypatch.setattr(
        channel._api,
        "send_group_text",
        lambda cid, text: groups.append((cid, text)) or {},
    )
    monkeypatch.setattr(
        channel._api,
        "send_oto_text",
        lambda *a, **k: otos.append((a, k)) or {},
    )
    channel.reply_text("group:cid-x", "结果已发送", at_user_ids=["staff-9"])
    assert groups == [("cid-x", "结果已发送")]
    assert otos == []


def test_broadcast_text_openapi_group_only(monkeypatch):
    channel = DingTalkChannel("cid", "secret", robot_code="bot")
    groups: list[str] = []
    otos: list = []

    monkeypatch.setattr(
        channel._api, "send_group_text", lambda cid, _t: groups.append(cid) or {}
    )
    monkeypatch.setattr(
        channel._api, "send_oto_text", lambda *a, **k: otos.append(a) or {}
    )
    channel.broadcast_text("group:cid-x", "bot offline")
    assert groups == ["cid-x"]
    assert otos == []
