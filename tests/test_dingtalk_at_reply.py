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
from channels.dingtalk.openapi import SessionReplyTarget
from channels.dingtalk.session_store import load_session_replies, save_session_replies


def test_extract_text_strips_at_tokens():
    msg = MagicMock()
    msg.text = MagicMock()
    msg.text.content = "@机器人 query progress"
    assert _extract_text(msg) == "query progress"


def test_reply_text_uses_session_webhook_with_at(monkeypatch):
    channel = DingTalkChannel("cid", "secret", robot_code="bot")
    calls: list[tuple] = []

    def _fake_reply(target, text, *, at_user_ids=None):
        calls.append((target, text, list(at_user_ids or [])))
        return {}

    monkeypatch.setattr(channel._api, "reply_session_text", _fake_reply)

    def _boom(*_a, **_k):
        raise AssertionError("openapi should not be used when sessionWebhook alive")

    monkeypatch.setattr(channel._api, "send_group_text", _boom)

    channel._session_replies["group:cid-x"] = SessionReplyTarget(
        webhook="https://example.com/session",
        expire_at_ms=9_999_999_999_999,
        sender_staff_id="staff-1",
        sender_nick="Alice",
    )
    channel.reply_text("group:cid-x", "hello", at_user_ids=["staff-1"])
    assert len(calls) == 1
    assert calls[0][1] == "hello"
    assert calls[0][2] == ["staff-1"]


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
    msg.session_webhook = "https://example.com/wh"
    msg.session_webhook_expired_time = 9_999_999_999_999
    msg.text = MagicMock()
    msg.text.content = "@bot query gid t-0001"

    channel.handle_incoming(msg)
    assert len(seen) == 1
    assert seen[0].chat_id == "group:cid-abc"
    assert seen[0].text == "query gid t-0001"
    assert seen[0].sender_id == "staff-9"
    assert seen[0].sender_name == "Bob"
    assert "group:cid-abc" in channel._session_replies


def test_session_store_survives_restart(tmp_path):
    path = tmp_path / "dingtalk_session_replies.json"
    target = SessionReplyTarget(
        webhook="https://example.com/wh",
        expire_at_ms=9_999_999_999_999,
        sender_staff_id="staff-2",
        sender_nick="Carol",
    )
    save_session_replies(path, {"group:cid-y": target})

    channel = DingTalkChannel(
        "cid",
        "secret",
        robot_code="bot",
        session_state_path=path,
    )
    loaded = channel._session_replies["group:cid-y"]
    assert loaded.webhook == target.webhook
    assert loaded.sender_staff_id == "staff-2"

    channel2 = DingTalkChannel(
        "cid",
        "secret",
        robot_code="bot",
        session_state_path=path,
    )
    assert channel2._session_replies["group:cid-y"].sender_nick == "Carol"
    assert load_session_replies(path)["group:cid-y"].expire_at_ms == target.expire_at_ms
