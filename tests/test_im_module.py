"""Unit tests for IM module parser / inbox / queue matching (no Feishu network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_IM_SRC = _ROOT / "apps" / "im-module" / "src"
_A_SRC = _ROOT / "apps" / "auto-extract" / "src"
_A_APP = _ROOT / "apps" / "auto-extract"
for p in (_IM_SRC, _A_SRC, _A_APP, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def test_parse_task_message_ok():
    from parser import parse_task_message

    text = 'hello\n{"get-texts":{"urls":[" https://a.apk "]}}\n'
    assert parse_task_message(text) == {"get-texts": {"urls": ["https://a.apk"]}}


def test_parse_task_message_code_fence():
    from parser import parse_task_message

    text = "```json\n{\"get-texts\":{\"urls\":[\"https://b.apk\"]}}\n```"
    assert parse_task_message(text)["get-texts"]["urls"] == ["https://b.apk"]


def test_parse_task_message_reject():
    from parser import parse_task_message

    assert parse_task_message("not json") is None
    assert parse_task_message("") is None
    assert parse_task_message('{"get-texts":{"urls":[]}}') is None


def test_parse_task_message_bare_urls():
    from parser import parse_task_message

    assert parse_task_message("https://a.apk") == {
        "get-texts": {"urls": ["https://a.apk"]}
    }
    multi = parse_task_message(
        "https://cdn.example.com/a.apk\nhttps://cdn.example.com/b.apk"
    )
    assert multi == {
        "get-texts": {
            "urls": [
                "https://cdn.example.com/a.apk",
                "https://cdn.example.com/b.apk",
            ]
        }
    }
    spaced = parse_task_message(
        "please https://x.apk https://y.apk, thanks"
    )
    assert spaced == {
        "get-texts": {"urls": ["https://x.apk", "https://y.apk"]}
    }
    # dedupe preserve order
    assert parse_task_message("https://a.apk https://a.apk https://b.apk") == {
        "get-texts": {"urls": ["https://a.apk", "https://b.apk"]}
    }


def test_write_inbox_json(tmp_path):
    from inbox_writer import write_inbox_json

    path = write_inbox_json(
        tmp_path,
        {"get-texts": {"urls": ["https://x.apk"]}},
        request_id="1_2",
    )
    assert path.name == "im_1_2.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["get-texts"]["urls"] == ["https://x.apk"]


def test_courier_delivers_each_finished_task(tmp_path, monkeypatch):
    """Undelivered terminal tasks are delivered from DB even after IM restart."""
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in (
        "config",
        "courier",
        "ops_commands",
        "task_ledger_query",
        "pending_inbox",
        "delivery_audit",
    ):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod
    import sqlite3
    assert "im-module" in (config.__file__ or "").replace("\\", "/")

    class _FakeChannel:
        def __init__(self):
            self.texts: list[tuple[str, str]] = []
            self.files: list[tuple[str, str]] = []

        def start(self, on_message):
            pass

        def stop(self):
            pass

        def reply_text(self, chat_id, text, *, at_user_ids=None):
            self.texts.append((chat_id, text))

        def send_file(self, chat_id, path):
            self.files.append((chat_id, Path(path).name))

    buf = tmp_path / "buf_done"
    buf.mkdir()
    (buf / "a.zip").write_bytes(b"a")
    (buf / "b.zip").write_bytes(b"b")
    db = tmp_path / "tasks.db"
    monkeypatch.setattr(config, "TASKS_DB", db)
    monkeypatch.setattr(config, "ZIP_WAIT_SEC", 600)
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_ID", "")
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_STATE", tmp_path / "announce.json")

    def _seed(rows: list[tuple]):
        conn = sqlite3.connect(str(db))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                url TEXT, label TEXT, filename TEXT, status TEXT, error TEXT,
                result_csv TEXT, session_id TEXT, buf_done_zip TEXT, source_file TEXT,
                adb_serial TEXT, created_at TEXT, updated_at TEXT, finished_at TEXT,
                im_delivered_at TEXT, im_chat_id TEXT
            )
            """
        )
        conn.execute("DELETE FROM tasks")
        for row in rows:
            conn.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                row,
            )
        conn.commit()
        conn.close()

    def _delivered(task_id: str) -> str:
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT im_delivered_at FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        conn.close()
        return (row[0] if row else "") or ""

    chat = "group:cid-x"
    ch = _FakeChannel()
    c = courier_mod.Courier(ch)

    _seed(
        [
            (
                "t-1",
                "https://x/a.apk",
                "game1",
                "a.apk",
                "success",
                "",
                "",
                "",
                str(buf / "a.zip"),
                "im_1000_1.json",
                "",
                "t0",
                "t1",
                "2026-01-01T00:00:00Z",
                "",
                chat,
            )
        ]
    )
    c._tick()
    assert _delivered("t-1")
    assert ch.files == [(chat, "a.zip")]
    assert any(chat == cid and "a.zip" in text for cid, text in ch.texts)

    # Simulate IM restart: new Courier, no memory; second task still undelivered.
    ch2 = _FakeChannel()
    c2 = courier_mod.Courier(ch2)
    _seed(
        [
            (
                "t-1",
                "https://x/a.apk",
                "game1",
                "a.apk",
                "success",
                "",
                "",
                "",
                str(buf / "a.zip"),
                "im_1000_1.json",
                "",
                "t0",
                "t1",
                "2026-01-01T00:00:00Z",
                "delivered",
                chat,
            ),
            (
                "t-2",
                "https://x/b.apk",
                "game2",
                "b.apk",
                "success",
                "",
                "",
                "",
                str(buf / "b.zip"),
                "im_1000_1.json",
                "",
                "t0",
                "t2",
                "2026-01-01T00:00:01Z",
                "",
                chat,
            ),
        ]
    )
    c2._tick()
    assert _delivered("t-2")
    assert ch2.files == [(chat, "b.zip")]
    c2._tick()
    assert ch2.files == [(chat, "b.zip")]


def test_enqueue_writes_im_chat_id(tmp_path, monkeypatch):
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in ("config", "courier", "inbox_writer"):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod

    class _FakeChannel:
        def start(self, on_message):
            pass

        def stop(self):
            pass

        def reply_text(self, chat_id, text, *, at_user_ids=None):
            pass

        def send_file(self, chat_id, path):
            pass

    inbox = tmp_path / "inbox"
    monkeypatch.setattr(config, "INBOX_DIR", inbox)
    c = courier_mod.Courier(_FakeChannel())
    path = c._enqueue_urls(
        "group:cid-z",
        ["https://a.apk", "https://b.apk"],
        sender_id="staff-z",
        ack=False,
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["get-texts"]["im_chat_id"] == "group:cid-z"
    assert data["get-texts"]["im_sender_id"] == "staff-z"
    assert data["get-texts"]["urls"] == ["https://a.apk", "https://b.apk"]


def test_enqueue_ack_mentions_core_down_once(tmp_path, monkeypatch):
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in ("config", "courier", "inbox_writer"):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod

    class _FakeChannel:
        def __init__(self):
            self.texts: list[tuple[str, str]] = []

        def start(self, on_message):
            pass

        def stop(self):
            pass

        def reply_text(self, chat_id, text, *, at_user_ids=None):
            self.texts.append((chat_id, text))

        def send_file(self, chat_id, path):
            pass

    inbox = tmp_path / "inbox"
    hb = tmp_path / "heartbeat"
    monkeypatch.setattr(config, "INBOX_DIR", inbox)
    monkeypatch.setattr(config, "CORE_HEARTBEAT_PATH", hb)
    monkeypatch.setattr(config, "CORE_SUBMIT_STALE_SEC", 10.0)
    monkeypatch.setattr(config, "CORE_HEARTBEAT_STALE_SEC", 15.0)
    ch = _FakeChannel()
    c = courier_mod.Courier(ch)

    # No heartbeat file → submit path treats core as down.
    c._enqueue_urls("group:cid-a", ["https://a.apk"], ack=True)
    assert len(ch.texts) == 1
    assert "已登记" in ch.texts[0][1]
    assert "处理服务暂不可用" in ch.texts[0][1]
    assert c._core_fault_announced is True

    # Poll must not broadcast a second core-down.
    c._check_core_health()
    assert len(ch.texts) == 1

    # Second submit: shorter note, still no extra global announce.
    c._enqueue_urls("group:cid-a", ["https://b.apk"], ack=True)
    assert len(ch.texts) == 2
    assert "恢复中" in ch.texts[1][1]
    c._check_core_health()
    assert len(ch.texts) == 2

    # Recovery → one up announce (to announce chat; may skip if none learned).
    hb.write_text("ok", encoding="utf-8")
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_ID", "group:cid-a")
    c._online_announced = True
    c._check_core_health()
    assert c._core_fault_announced is False
    assert any("继续" in t or "恢复" in t or "修好" in t or "搞定" in t or "活过来" in t for _, t in ch.texts)


def test_create_channel_routes():
    from types import SimpleNamespace

    from channels.factory import create_channel

    ch = create_channel(
        SimpleNamespace(
            IM_CHANNEL="feishu",
            FEISHU_APP_ID="cli_x",
            FEISHU_APP_SECRET="sec",
        )
    )
    assert ch.__class__.__name__ == "FeishuChannel"

    try:
        create_channel(
            SimpleNamespace(
                IM_CHANNEL="dingtalk",
                DINGTALK_CLIENT_ID="",
                DINGTALK_CLIENT_SECRET="",
                DINGTALK_ROBOT_CODE="",
            )
        )
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert "DINGTALK" in str(exc)

    ding = create_channel(
        SimpleNamespace(
            IM_CHANNEL="dingtalk",
            DINGTALK_CLIENT_ID="ding_id",
            DINGTALK_CLIENT_SECRET="ding_sec",
            DINGTALK_ROBOT_CODE="",
        )
    )
    assert ding.__class__.__name__ == "DingTalkChannel"

    try:
        create_channel(SimpleNamespace(IM_CHANNEL="unknown"))
        assert False, "expected SystemExit"
    except SystemExit:
        pass


def test_queue_manager_snapshot(tmp_path, monkeypatch):
    # Prefer auto-extract config/queue_manager over im-module when paths collide.
    for p in (str(_A_SRC), str(_A_APP)):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    cfg = sys.modules.get("config")
    if cfg is not None and "auto-extract" not in (cfg.__file__ or ""):
        for name in ("config", "queue_manager", "task_store", "pipeline_queues"):
            sys.modules.pop(name, None)

    import config
    import queue_manager as qm
    import task_store

    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "QUEUE_STATUS_FILE", tmp_path / "queue_status.json")
    monkeypatch.setattr(config, "BUF_DONE_DIR", tmp_path / "buf_done")
    monkeypatch.setattr(config, "TASKS_DB", tmp_path / "tasks.db")
    monkeypatch.setattr(config, "QUEUE_RECENT_DONE_MAX", 10)
    task_store._conn = None
    qm.load()
    created = qm.enqueue_urls(["https://g.apk"], "im_demo.json")
    assert qm.get_task(created[0].task_id) is not None
    assert qm.get_task("missing") is None
    snap = json.loads(config.QUEUE_STATUS_FILE.read_text(encoding="utf-8"))
    assert snap["active"][0]["source_file"] == "im_demo.json"
    qm.update_task(
        created[0].task_id,
        status="success",
        result_csv=str(tmp_path / "result" / "stem_label.csv"),
    )
    # Terminal leaves memory active list, but remains readable from DB.
    assert created[0].task_id not in {t.task_id for t in qm.list_tasks()}
    done = qm.get_task(created[0].task_id)
    assert done is not None and done.status == "success"
    snap = json.loads(config.QUEUE_STATUS_FILE.read_text(encoding="utf-8"))
    assert snap["active"] == []
    assert snap["recent_done"][0]["status"] == "success"
    assert snap["recent_done"][0]["buf_done_zip"].endswith("stem_label.zip")


def test_courier_core_health_edge_announce(tmp_path, monkeypatch):
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in ("config", "courier"):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod

    class _FakeChannel:
        def __init__(self):
            self.texts: list[tuple[str, str]] = []

        def start(self, on_message):
            pass

        def stop(self):
            pass

        def reply_text(self, chat_id, text, *, at_user_ids=None):
            self.texts.append((chat_id, text))

        def send_file(self, chat_id, path):
            pass

    hb = tmp_path / "heartbeat"
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_ID", "group:cid-test")
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_STATE", tmp_path / "announce.json")
    monkeypatch.setattr(config, "CORE_HEARTBEAT_PATH", hb)
    monkeypatch.setattr(config, "CORE_HEARTBEAT_STALE_SEC", 45.0)
    monkeypatch.setattr(config, "INBOX_DIR", tmp_path / "inbox")
    monkeypatch.setattr(config, "PENDING_INBOX_STATE", tmp_path / "pending_inbox.json")
    (tmp_path / "inbox").mkdir()

    ch = _FakeChannel()
    c = courier_mod.Courier(ch)

    # Before online intro, core-down must stay silent.
    c._check_core_health()
    assert ch.texts == []

    # Online first, then one fault (folded into announce_online).
    c._announce_online()
    assert len(ch.texts) >= 2
    assert "用法" in ch.texts[0][1]
    assert ch.texts[1][1] in config.MSG_CORE_DOWN_VARIANTS
    fault_msg = ch.texts[1][1]
    before = list(ch.texts)
    c._check_core_health()
    assert ch.texts == before

    # Fresh heartbeat → one recover (may be followed by pending reconcile notices)
    hb.write_text("ok\n", encoding="utf-8")
    c._check_core_health()
    up_msgs = [t for t in ch.texts if t[1] in config.MSG_CORE_UP_VARIANTS]
    assert len(up_msgs) == 1
    assert up_msgs[0][0] == "group:cid-test"
    up_msg = up_msgs[0][1]
    c._check_core_health()
    assert len([t for t in ch.texts if t[1] == up_msg]) == 1

    # Empty announce chat → skip without crash
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_ID", "")
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_STATE", tmp_path / "announce_chat.json")
    ch.texts.clear()
    c._online_announced = False
    c._core_fault_announced = False
    hb.unlink()
    c._check_core_health()
    assert ch.texts == []

    # Learn from first inbound → online, then core-down (still after intro).
    from channels.base import IncomingChat

    c.on_message(
        IncomingChat(chat_id="group:cid-learned", text="help", sender_id="u1")
    )
    assert any("用法" in t for _, t in ch.texts)
    down_idxs = [
        i
        for i, (_, t) in enumerate(ch.texts)
        if t in config.MSG_CORE_DOWN_VARIANTS
    ]
    online_idxs = [i for i, (_, t) in enumerate(ch.texts) if "用法" in t]
    assert down_idxs and online_idxs and down_idxs[0] > online_idxs[0]


def test_announce_chat_accumulates_groups(tmp_path):
    from announce_chat import (
        add_announce_chat,
        load_learned_chats,
        resolve_announce_chats,
    )

    path = tmp_path / "announce.json"
    assert add_announce_chat(path, "group:A") is True
    assert add_announce_chat(path, "group:B") is True
    assert add_announce_chat(path, "group:A") is False
    assert load_learned_chats(path) == ["group:A", "group:B"]
    assert resolve_announce_chats(pinned="group:P", state_path=path) == [
        "group:P",
        "group:A",
        "group:B",
    ]


def test_announce_broadcasts_to_all_known_chats(tmp_path, monkeypatch):
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in ("config", "courier", "announce_chat"):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod
    from announce_chat import add_announce_chat

    class _FakeChannel:
        def __init__(self):
            self.texts: list[tuple[str, str]] = []

        def start(self, on_message):
            pass

        def stop(self):
            pass

        def reply_text(self, chat_id, text, *, at_user_ids=None):
            self.texts.append((chat_id, text))

        def send_file(self, chat_id, path):
            pass

    state = tmp_path / "announce.json"
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_ID", "")
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_STATE", state)
    add_announce_chat(state, "group:A")
    add_announce_chat(state, "group:B")
    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    assert c._announce("fault-notice") is True
    chats = {cid for cid, _ in ch.texts}
    assert chats == {"group:A", "group:B"}
    assert all(t == "fault-notice" for _, t in ch.texts)


def test_deliver_fail_closed_without_im_chat_id(tmp_path, monkeypatch):
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in ("config", "courier", "delivery_audit"):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod
    import sqlite3

    class _FakeChannel:
        def __init__(self):
            self.texts: list = []
            self.files: list = []

        def start(self, on_message):
            pass

        def stop(self):
            pass

        def reply_text(self, chat_id, text, *, at_user_ids=None):
            self.texts.append((chat_id, text))

        def send_file(self, chat_id, path):
            self.files.append((chat_id, Path(path).name))

    db = tmp_path / "tasks.db"
    audit = tmp_path / "delivery_audit.jsonl"
    monkeypatch.setattr(config, "TASKS_DB", db)
    monkeypatch.setattr(config, "DELIVERY_AUDIT_PATH", audit)
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_ID", "group:announce")
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_STATE", tmp_path / "announce.json")
    monkeypatch.setattr(config, "ZIP_WAIT_SEC", 600)

    conn = sqlite3.connect(str(db))
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
        "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "t-orphan",
            "https://x/a.apk",
            "g",
            "a.apk",
            "failed",
            "x",
            "",
            "",
            "",
            "",
            "",
            "t0",
            "t1",
            "2026-01-01T00:00:00Z",
            "",
            "",
            "staff-1",
            "",
        ),
    )
    conn.commit()
    conn.close()

    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    c._tick()
    assert ch.files == []
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT im_delivered_at, im_deliver_error FROM tasks WHERE task_id=?",
        ("t-orphan",),
    ).fetchone()
    conn.close()
    assert row[0]
    assert "abandoned" in (row[1] or "")
    assert "im_chat_id" in (row[1] or "")
    assert audit.is_file()
    assert "missing_im_chat_id" in audit.read_text(encoding="utf-8")


def test_pending_inbox_rewritten_when_missing_after_core_up(tmp_path, monkeypatch):
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in ("config", "courier", "pending_inbox", "inbox_writer"):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod
    from pending_inbox import add_pending, list_pending

    class _FakeChannel:
        def __init__(self):
            self.texts: list[tuple[str, str]] = []

        def start(self, on_message):
            pass

        def stop(self):
            pass

        def reply_text(self, chat_id, text, *, at_user_ids=None):
            self.texts.append((chat_id, text))

        def send_file(self, chat_id, path):
            pass

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    state = tmp_path / "pending_inbox.json"
    hb = tmp_path / "heartbeat"
    hb.write_text("ok", encoding="utf-8")
    monkeypatch.setattr(config, "INBOX_DIR", inbox)
    monkeypatch.setattr(config, "PENDING_INBOX_STATE", state)
    monkeypatch.setattr(config, "CORE_HEARTBEAT_PATH", hb)
    monkeypatch.setattr(config, "TASKS_DB", tmp_path / "missing.db")
    monkeypatch.setattr(config, "PENDING_INBOX_RESUBMIT_MAX", 3)

    filename = "im_1000_1.json"
    add_pending(
        state,
        filename=filename,
        inbox_path=str(inbox / filename),
        chat_id="group:cid-a",
        sender_id="staff-1",
        urls=["https://cdn.example.com/a.apk"],
        route="get-texts",
    )
    assert not (inbox / filename).exists()

    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    c._reconcile_pending_inbox(force_resubmit=True)
    rewritten = inbox / filename
    assert rewritten.is_file()
    data = json.loads(rewritten.read_text(encoding="utf-8"))
    assert data["get-texts"]["urls"] == ["https://cdn.example.com/a.apk"]
    assert any("继续处理" in t or "已恢复" in t for _, t in ch.texts)
    assert list_pending(state)[0]["resubmit_count"] == 1


def test_deliver_file_ok_text_fail_marks_delivered_once(tmp_path, monkeypatch):
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in ("config", "courier", "delivery_audit"):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod
    import sqlite3

    class _FakeChannel:
        def __init__(self):
            self.files: list = []
            self._text_fail = True

        def start(self, on_message):
            pass

        def stop(self):
            pass

        def reply_text(self, chat_id, text, *, at_user_ids=None):
            if self._text_fail:
                raise RuntimeError("text boom")

        def send_file(self, chat_id, path):
            self.files.append((chat_id, Path(path).name))

    buf = tmp_path / "buf"
    buf.mkdir()
    (buf / "a.zip").write_bytes(b"a")
    db = tmp_path / "tasks.db"
    audit = tmp_path / "delivery_audit.jsonl"
    monkeypatch.setattr(config, "TASKS_DB", db)
    monkeypatch.setattr(config, "DELIVERY_AUDIT_PATH", audit)
    monkeypatch.setattr(config, "ZIP_WAIT_SEC", 600)

    conn = sqlite3.connect(str(db))
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
    chat = "group:cid-x"
    conn.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "t-1",
            "https://x/a.apk",
            "g",
            "a.apk",
            "success",
            "",
            "",
            "",
            str(buf / "a.zip"),
            "",
            "",
            "t0",
            "t1",
            "2026-01-01T00:00:00Z",
            "",
            chat,
            "staff-1",
            "",
        ),
    )
    conn.commit()
    conn.close()

    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    c._tick()
    assert ch.files == [(chat, "a.zip")]
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT im_delivered_at, im_deliver_error FROM tasks WHERE task_id=?",
        ("t-1",),
    ).fetchone()
    conn.close()
    assert row[0]
    assert "text boom" in (row[1] or "")
    c._tick()
    assert ch.files == [(chat, "a.zip")]
    assert "file_ok_text_failed" in audit.read_text(encoding="utf-8")
