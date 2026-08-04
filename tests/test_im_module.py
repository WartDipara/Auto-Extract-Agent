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
    """One inbox with N urls must reply as each task finishes, not only the last."""
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    cfg = sys.modules.get("config")
    if cfg is not None and "im-module" not in (cfg.__file__ or ""):
        for name in ("config", "courier", "ops_commands", "task_ledger_query"):
            sys.modules.pop(name, None)

    import config
    import courier as courier_mod
    import sqlite3

    class _FakeChannel:
        def __init__(self):
            self.texts: list[str] = []
            self.files: list[str] = []

        def start(self, on_message):
            pass

        def reply_text(self, chat_id, text):
            self.texts.append(text)

        def send_file(self, chat_id, path):
            self.files.append(Path(path).name)

    buf = tmp_path / "buf_done"
    buf.mkdir()
    (buf / "a.bin").write_bytes(b"a")
    (buf / "b.bin").write_bytes(b"b")
    db = tmp_path / "tasks.db"
    monkeypatch.setattr(config, "TASKS_DB", db)
    monkeypatch.setattr(config, "ZIP_WAIT_SEC", 600)

    def _seed(rows: list[tuple]):
        conn = sqlite3.connect(str(db))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                url TEXT, label TEXT, filename TEXT, status TEXT, error TEXT,
                result_csv TEXT, session_id TEXT, buf_done_zip TEXT, source_file TEXT,
                adb_serial TEXT, created_at TEXT, updated_at TEXT, finished_at TEXT,
                im_delivered_at TEXT
            )
            """
        )
        conn.execute("DELETE FROM tasks")
        for row in rows:
            conn.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                row,
            )
        conn.commit()
        conn.close()

    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    job = courier_mod.PendingJob(
        request_id="1000_1",
        chat_id="oc_x",
        source_file="im_1000_1.json",
        expected=2,
    )
    c._jobs[job.request_id] = job

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
                str(buf / "a.bin"),
                "im_1000_1.json",
                "",
                "t0",
                "t1",
                "t1",
                "",
            )
        ]
    )
    c._tick()
    assert job.delivered_ids == {"t-1"}
    assert not job.finished
    assert ch.files == ["a.bin"]
    assert any("a.bin" in t for t in ch.texts)

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
                str(buf / "a.bin"),
                "im_1000_1.json",
                "",
                "t0",
                "t1",
                "t1",
                "delivered",
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
                str(buf / "b.bin"),
                "im_1000_1.json",
                "",
                "t0",
                "t2",
                "t2",
                "",
            ),
        ]
    )
    c._tick()
    assert job.delivered_ids == {"t-1", "t-2"}
    assert job.finished
    assert ch.files == ["a.bin", "b.bin"]

    c._tick()
    assert ch.files == ["a.bin", "b.bin"]


def test_create_channel_routes(monkeypatch):
    from channels.factory import create_channel

    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "sec")
    ch = create_channel("feishu")
    assert ch.__class__.__name__ == "FeishuChannel"

    for key in (
        "DINGTALK_CLIENT_ID",
        "DINGTALK_CLIENT_SECRET",
        "DINGTALK_APP_KEY",
        "DINGTALK_APP_SECRET",
        "DINGTALK_ROBOT_CODE",
    ):
        monkeypatch.delenv(key, raising=False)
    try:
        create_channel("dingtalk")
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert "DINGTALK" in str(exc)

    monkeypatch.setenv("DINGTALK_CLIENT_ID", "ding_id")
    monkeypatch.setenv("DINGTALK_CLIENT_SECRET", "ding_sec")
    ding = create_channel("dingtalk")
    assert ding.__class__.__name__ == "DingTalkChannel"

    try:
        create_channel("unknown")
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
    assert snap["recent_done"][0]["buf_done_zip"].endswith("stem_label.bin")
