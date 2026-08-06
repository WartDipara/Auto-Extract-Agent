from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_IM_SRC = _ROOT / "apps" / "im-module" / "src"
for p in (_IM_SRC, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def test_looks_like_dead_chat_dingtalk_body():
    from channels.dingtalk.openapi import looks_like_dead_chat

    body = (
        '{"code":"resource.not.found",'
        '"message":"错误描述: robot 不存在；解决方案:请确认 robotCode 是否正确；"}'
    )
    assert looks_like_dead_chat(body) is True
    assert looks_like_dead_chat("ok") is False


def test_remove_announce_chat(tmp_path):
    from announce_chat import (
        add_announce_chat,
        load_learned_chats,
        remove_announce_chat,
    )

    path = tmp_path / "announce.json"
    add_announce_chat(path, "group:A")
    add_announce_chat(path, "group:B")
    assert remove_announce_chat(path, "group:A") is True
    assert load_learned_chats(path) == ["group:B"]
    assert remove_announce_chat(path, "group:A") is False


def test_announce_drops_dead_chat(tmp_path, monkeypatch):
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in ("config", "courier", "announce_chat"):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod
    from announce_chat import add_announce_chat, load_learned_chats
    from channels.dingtalk.openapi import DingTalkDeadChatError

    class _FakeChannel:
        def __init__(self):
            self.ok: list[str] = []

        def broadcast_text(self, chat_id, text):
            if chat_id == "group:dead":
                raise DingTalkDeadChatError("resource.not.found robot 不存在")
            self.ok.append(chat_id)

        def reply_text(self, *a, **k):
            raise AssertionError("use broadcast")

        def stop(self):
            pass

        def start(self, on_message):
            pass

        def send_file(self, *a, **k):
            pass

    state = tmp_path / "announce.json"
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_ID", "")
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_STATE", state)
    add_announce_chat(state, "group:dead")
    add_announce_chat(state, "group:live")
    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    assert c._announce("hello") is True
    assert ch.ok == ["group:live"]
    assert load_learned_chats(state) == ["group:live"]


def test_dead_chat_deliver_abandons_and_otos(tmp_path, monkeypatch):
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in ("config", "courier", "announce_chat"):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod
    from channels.dingtalk.openapi import DingTalkDeadChatError

    class _FakeChannel:
        def __init__(self):
            self.texts: list[tuple[str, str]] = []

        def reply_text(self, chat_id, text, *, at_user_ids=None):
            if chat_id.startswith("group:"):
                raise DingTalkDeadChatError("resource.not.found robot 不存在")
            self.texts.append((chat_id, text))

        def send_file(self, chat_id, path):
            pass

        def broadcast_text(self, chat_id, text):
            self.reply_text(chat_id, text)

        def stop(self):
            pass

        def start(self, on_message):
            pass

    db = tmp_path / "tasks.db"
    monkeypatch.setattr(config, "TASKS_DB", db)
    monkeypatch.setattr(config, "TASKS_TABLE", "tasks")
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_STATE", tmp_path / "announce.json")
    monkeypatch.setattr(config, "DELIVERY_AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "FILE_SENT_STATE", tmp_path / "file_sent.json")

    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY, url TEXT, label TEXT, filename TEXT,
            status TEXT, error TEXT, result_csv TEXT, session_id TEXT,
            buf_done_zip TEXT, source_file TEXT, adb_serial TEXT,
            created_at TEXT, updated_at TEXT, finished_at TEXT,
            im_delivered_at TEXT, im_chat_id TEXT, im_sender_id TEXT,
            im_deliver_error TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO tasks (
            task_id, url, label, filename, status, error, result_csv,
            session_id, buf_done_zip, source_file, adb_serial,
            created_at, updated_at, finished_at,
            im_delivered_at, im_chat_id, im_sender_id, im_deliver_error
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "t-dead",
            "https://x/a.apk",
            "Game",
            "a.apk",
            "failed",
            "boom",
            "",
            "",
            "",
            "",
            "",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            "",
            "group:dead",
            "staff-1",
            "",
        ),
    )
    conn.commit()
    conn.close()

    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    done = {
        "task_id": "t-dead",
        "status": "failed",
        "error": "boom",
        "label": "Game",
        "im_chat_id": "group:dead",
        "im_sender_id": "staff-1",
        "_tasks_table": "tasks",
    }
    assert c._deliver_done("group:dead", done) is True
    assert any(cid == "oto:staff-1" for cid, _ in ch.texts)
    row = sqlite3.connect(db).execute(
        "SELECT im_delivered_at, im_deliver_error FROM tasks WHERE task_id='t-dead'"
    ).fetchone()
    assert row[0]
    assert "chat gone" in (row[1] or "") or "robot left" in (row[1] or "")
