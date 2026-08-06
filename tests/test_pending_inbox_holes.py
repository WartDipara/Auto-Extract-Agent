"""Logic-hole guards for pending inbox / request id / corrupt ledger."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_IM_SRC = _ROOT / "apps" / "im-module" / "src"
for p in (_IM_SRC, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def test_pending_corrupt_quarantined_not_wiped(tmp_path):
    from pending_inbox import add_pending, list_pending

    path = tmp_path / "pending_inbox.json"
    path.write_text("{not-json", encoding="utf-8")
    add_pending(
        path,
        filename="im_1.json",
        inbox_path=str(tmp_path / "im_1.json"),
        chat_id="group:a",
        sender_id="u1",
        urls=["https://a.apk"],
        route="get-texts",
    )
    assert list_pending(path)[0]["filename"] == "im_1.json"
    corrupt = list(tmp_path.glob("pending_inbox.json.corrupt-*"))
    assert corrupt, "corrupt file should be quarantined"


def test_new_request_id_not_mod_million():
    from inbox_writer import new_request_id

    a = new_request_id()
    b = new_request_id()
    assert a != b
    assert a.startswith(tuple("0123456789"))
    # uuid hex tail is longer than old 6-digit wrap
    assert len(a.split("_", 1)[1]) >= 12


def test_enqueue_tracks_pending_before_write(tmp_path, monkeypatch):
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in ("config", "courier", "pending_inbox", "inbox_writer"):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod
    from pending_inbox import list_pending

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
    state = tmp_path / "pending.json"
    monkeypatch.setattr(config, "INBOX_DIR", inbox)
    monkeypatch.setattr(config, "PENDING_INBOX_STATE", state)
    monkeypatch.setattr(config, "INBOX_ROUTE", "get-texts")
    c = courier_mod.Courier(_FakeChannel())
    path = c._enqueue_urls(
        "group:x", ["https://a.apk"], sender_id="s1", ack=False
    )
    assert path.is_file()
    items = list_pending(state)
    assert len(items) == 1
    assert items[0]["urls"] == ["https://a.apk"]
    assert items[0]["filename"] == path.name


def test_zip_timeout_keeps_undelivered(tmp_path, monkeypatch):
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
            self.texts = []

        def start(self, on_message):
            pass

        def stop(self):
            pass

        def reply_text(self, chat_id, text, *, at_user_ids=None):
            self.texts.append(text)

        def send_file(self, chat_id, path):
            raise AssertionError("should not send missing file")

    db = tmp_path / "tasks.db"
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(config, "TASKS_DB", db)
    monkeypatch.setattr(config, "DELIVERY_AUDIT_PATH", audit)
    monkeypatch.setattr(config, "ZIP_WAIT_SEC", 0.0)

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
    missing = tmp_path / "nope.zip"
    conn.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "t-z",
            "https://x/a.apk",
            "g",
            "a.apk",
            "success",
            "",
            "",
            "",
            str(missing),
            "",
            "",
            "t0",
            "t1",
            "2020-01-01T00:00:00Z",
            "",
            "group:cid",
            "staff",
            "",
        ),
    )
    conn.commit()
    conn.close()

    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    c._tick()
    row = sqlite3.connect(str(db)).execute(
        "SELECT im_delivered_at, im_deliver_error FROM tasks WHERE task_id='t-z'"
    ).fetchone()
    assert row[0]
    assert "abandoned" in (row[1] or "")
    assert any("停止回传" in t or "放弃" in t for t in ch.texts)
    assert "zip_missing_abandoned" in audit.read_text(encoding="utf-8")
