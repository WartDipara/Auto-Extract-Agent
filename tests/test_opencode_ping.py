"""OpenCode ping health helper + IM command wiring."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
_IM_SRC = _ROOT / "apps" / "im-module" / "src"
for p in (_IM_SRC, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def test_looks_like_pong_and_parse():
    from shared.opencode_health import _looks_like_pong, _parse_text_event

    assert _looks_like_pong("pong")
    assert _looks_like_pong("Pong!")
    assert not _looks_like_pong("ok")
    line = json.dumps({"type": "text", "part": {"text": "pong"}})
    assert _parse_text_event(line) == "pong"


def test_ping_opencode_ok(monkeypatch, tmp_path):
    from shared import opencode_health as oh

    payload = (
        json.dumps({"type": "text", "part": {"text": "pong"}}) + "\n"
    ).encode("utf-8")

    def _fake_run(argv, **kwargs):
        assert "run" in argv
        assert any("pong" in str(a).lower() or "Reply" in str(a) for a in argv)
        return SimpleNamespace(returncode=0, stdout=payload, stderr=b"")

    monkeypatch.setattr(oh.subprocess, "run", _fake_run)
    monkeypatch.setattr(oh.shutil, "which", lambda _c: "opencode")
    result = oh.ping_opencode(cmd="opencode", cwd=tmp_path, timeout_sec=10)
    assert result.ok
    assert result.message == "pong"


def test_ping_opencode_bad_reply(monkeypatch, tmp_path):
    from shared import opencode_health as oh

    payload = (
        json.dumps({"type": "text", "part": {"text": "hello"}}) + "\n"
    ).encode("utf-8")

    monkeypatch.setattr(
        oh.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(
            returncode=0, stdout=payload, stderr=b""
        ),
    )
    monkeypatch.setattr(oh.shutil, "which", lambda _c: "opencode")
    result = oh.ping_opencode(cwd=tmp_path, timeout_sec=10)
    assert not result.ok
    assert "pong" in result.message.lower() or "未返回" in result.message


def test_ping_opencode_timeout(monkeypatch, tmp_path):
    from shared import opencode_health as oh

    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="opencode", timeout=1)

    monkeypatch.setattr(oh.subprocess, "run", _boom)
    monkeypatch.setattr(oh.shutil, "which", lambda _c: "opencode")
    result = oh.ping_opencode(cwd=tmp_path, timeout_sec=1)
    assert not result.ok
    assert "超时" in result.message


def test_courier_ping_replies_pong(tmp_path, monkeypatch):
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in ("config", "courier", "ops_commands"):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod
    from channels.base import IncomingChat
    from shared.opencode_health import OpenCodePingResult

    class _FakeChannel:
        def __init__(self):
            self.texts: list[str] = []

        def start(self, on_message):
            pass

        def stop(self):
            pass

        def reply_text(self, chat_id, text, *, at_user_ids=None):
            self.texts.append(text)

        def send_file(self, chat_id, path):
            pass

    monkeypatch.setattr(config, "ANNOUNCE_CHAT_ID", "")
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_STATE", tmp_path / "a.json")
    monkeypatch.setattr(config, "OPENCODE_PING_DIR", tmp_path / "ping")
    monkeypatch.setattr(config, "OPENCODE_PING_TIMEOUT_SEC", 5)
    monkeypatch.setattr(
        courier_mod,
        "ping_opencode",
        lambda **_k: OpenCodePingResult(ok=True, message="pong"),
    )
    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    c._online_announced = True  # skip lifecycle greet noise
    c.on_message(IncomingChat(chat_id="group:x", text="ping", sender_id="u1"))
    assert "正在检查 OpenCode…" in ch.texts
    assert ch.texts[-1] == "pong"
