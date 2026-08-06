"""IM robustness: deliver abandon, no resend after file_sent, Feishu reconnect."""

from __future__ import annotations

import sqlite3
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]
_IM_SRC = _ROOT / "apps" / "im-module" / "src"
for p in (_IM_SRC, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _load_courier(tmp_path, monkeypatch):
    for p in list(sys.path):
        if "auto-extract" in p.replace("\\", "/"):
            sys.path.remove(p)
    if str(_IM_SRC) not in sys.path:
        sys.path.insert(0, str(_IM_SRC))
    for name in (
        "config",
        "courier",
        "delivery_audit",
        "pending_inbox",
        "channels.feishu",
    ):
        sys.modules.pop(name, None)

    import config
    import courier as courier_mod

    db = tmp_path / "tasks.db"
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(config, "TASKS_DB", db)
    monkeypatch.setattr(config, "DELIVERY_AUDIT_PATH", audit)
    monkeypatch.setattr(config, "FILE_SENT_STATE", tmp_path / "file_sent.json")
    monkeypatch.setattr(config, "ZIP_WAIT_SEC", 0.0)
    monkeypatch.setattr(config, "DELIVER_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_ID", "")
    monkeypatch.setattr(config, "ANNOUNCE_CHAT_STATE", tmp_path / "announce.json")
    return config, courier_mod, db, audit


def _seed_task(db: Path, **fields):
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY, url TEXT, label TEXT, filename TEXT,
            status TEXT, error TEXT, result_csv TEXT, session_id TEXT,
            buf_done_zip TEXT, source_file TEXT, adb_serial TEXT,
            created_at TEXT, updated_at TEXT, finished_at TEXT,
            im_delivered_at TEXT, im_chat_id TEXT, im_sender_id TEXT,
            im_deliver_error TEXT
        )
        """
    )
    defaults = {
        "task_id": "t-1",
        "url": "https://x/a.apk",
        "label": "g",
        "filename": "a.apk",
        "status": "success",
        "error": "",
        "result_csv": "",
        "session_id": "",
        "buf_done_zip": "",
        "source_file": "",
        "adb_serial": "",
        "created_at": "t0",
        "updated_at": "t1",
        "finished_at": "2020-01-01T00:00:00Z",
        "im_delivered_at": "",
        "im_chat_id": "group:cid",
        "im_sender_id": "staff",
        "im_deliver_error": "",
    }
    defaults.update(fields)
    cols = list(defaults.keys())
    conn.execute(
        f"INSERT OR REPLACE INTO tasks ({','.join(cols)}) "
        f"VALUES ({','.join('?' for _ in cols)})",
        [defaults[c] for c in cols],
    )
    conn.commit()
    conn.close()


class _FakeChannel:
    def __init__(self):
        self.texts = []
        self.files = []
        self.send_file_exc: Exception | None = None
        self.mark_path: Path | None = None

    def start(self, on_message):
        pass

    def stop(self):
        pass

    def reply_text(self, chat_id, text, *, at_user_ids=None):
        self.texts.append(text)

    def send_file(self, chat_id, path):
        if self.send_file_exc is not None:
            raise self.send_file_exc
        self.files.append(Path(path).name)


def test_missing_chat_abandoned(tmp_path, monkeypatch):
    _config, courier_mod, db, audit = _load_courier(tmp_path, monkeypatch)
    _seed_task(db, im_chat_id="")
    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    c._tick()
    row = sqlite3.connect(str(db)).execute(
        "SELECT im_delivered_at, im_deliver_error FROM tasks WHERE task_id='t-1'"
    ).fetchone()
    assert row[0]
    assert "abandoned" in (row[1] or "")
    assert "missing_im_chat_id" in audit.read_text(encoding="utf-8")


def test_zip_missing_after_wait_abandoned(tmp_path, monkeypatch):
    _config, courier_mod, db, audit = _load_courier(tmp_path, monkeypatch)
    missing = tmp_path / "nope.bin"
    _seed_task(db, buf_done_zip=str(missing))
    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    c._tick()
    row = sqlite3.connect(str(db)).execute(
        "SELECT im_delivered_at, im_deliver_error FROM tasks WHERE task_id='t-1'"
    ).fetchone()
    assert row[0]
    assert "abandoned" in (row[1] or "")
    assert "zip_missing_abandoned" in audit.read_text(encoding="utf-8")


def test_file_send_max_attempts_abandoned(tmp_path, monkeypatch):
    _config, courier_mod, db, _audit = _load_courier(tmp_path, monkeypatch)
    z = tmp_path / "a.bin"
    z.write_bytes(b"x")
    _seed_task(db, buf_done_zip=str(z))
    ch = _FakeChannel()
    ch.send_file_exc = RuntimeError("temporary network")
    c = courier_mod.Courier(ch)
    c._tick()
    row = sqlite3.connect(str(db)).execute(
        "SELECT im_delivered_at FROM tasks WHERE task_id='t-1'"
    ).fetchone()
    assert (row[0] or "") == ""
    c._tick()
    row = sqlite3.connect(str(db)).execute(
        "SELECT im_delivered_at, im_deliver_error FROM tasks WHERE task_id='t-1'"
    ).fetchone()
    assert row[0]
    assert "abandoned" in (row[1] or "")


def test_file_sent_mark_fail_does_not_resend(tmp_path, monkeypatch):
    _config, courier_mod, db, _audit = _load_courier(tmp_path, monkeypatch)
    z = tmp_path / "a.bin"
    z.write_bytes(b"x")
    _seed_task(db, buf_done_zip=str(z))
    ch = _FakeChannel()
    c = courier_mod.Courier(ch)

    real_mark = courier_mod._mark_delivered
    calls = {"n": 0}

    def _flaky_mark(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db locked")
        return real_mark(*args, **kwargs)

    monkeypatch.setattr(courier_mod, "_mark_delivered", _flaky_mark)
    c._tick()
    assert ch.files == ["a.bin"]
    row = sqlite3.connect(str(db)).execute(
        "SELECT im_delivered_at FROM tasks WHERE task_id='t-1'"
    ).fetchone()
    assert (row[0] or "") == ""
    assert "t-1" in c._file_sent_ok

    c._tick()
    assert ch.files == ["a.bin"]  # no second send
    row = sqlite3.connect(str(db)).execute(
        "SELECT im_delivered_at FROM tasks WHERE task_id='t-1'"
    ).fetchone()
    assert row[0]


def test_non_retryable_file_error_abandons_immediately(tmp_path, monkeypatch):
    _config, courier_mod, db, _audit = _load_courier(tmp_path, monkeypatch)
    z = tmp_path / "a.bin"
    z.write_bytes(b"x")
    _seed_task(db, buf_done_zip=str(z))
    ch = _FakeChannel()
    ch.send_file_exc = RuntimeError("file too large > 20MB")
    c = courier_mod.Courier(ch)
    c._tick()
    row = sqlite3.connect(str(db)).execute(
        "SELECT im_delivered_at, im_deliver_error FROM tasks WHERE task_id='t-1'"
    ).fetchone()
    assert row[0]
    assert "abandoned" in (row[1] or "")


def test_feishu_start_reconnect_loop_can_stop(monkeypatch):
    for p in list(sys.path):
        if "auto-extract" in p.replace("\\", "/"):
            sys.path.remove(p)
    if str(_IM_SRC) not in sys.path:
        sys.path.insert(0, str(_IM_SRC))
    sys.modules.pop("channels.feishu", None)
    sys.modules.pop("config", None)

    import config

    monkeypatch.setattr(config, "FEISHU_RECONNECT_SEC", 0.05)

    class _Builder:
        def app_id(self, *_a):
            return self

        def app_secret(self, *_a):
            return self

        def log_level(self, *_a):
            return self

        def build(self):
            return object()

        def register_p2_im_message_receive_v1(self, _fn):
            return self

    starts = {"n": 0}

    class _Cli:
        def start(self):
            starts["n"] += 1

    import channels.feishu as feishu_mod

    monkeypatch.setattr(
        feishu_mod.lark.Client, "builder", staticmethod(lambda: _Builder())
    )
    monkeypatch.setattr(
        feishu_mod.lark.EventDispatcherHandler,
        "builder",
        staticmethod(lambda *_a, **_k: _Builder()),
    )
    monkeypatch.setattr(feishu_mod.lark.ws, "Client", lambda *a, **k: _Cli())

    ch = feishu_mod.FeishuChannel("id", "secret")

    def _run():
        ch.start(lambda _msg: None)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    deadline = time.time() + 2.0
    while starts["n"] < 2 and time.time() < deadline:
        time.sleep(0.05)
    ch.stop()
    t.join(timeout=2.0)
    assert starts["n"] >= 2
    assert not t.is_alive()
