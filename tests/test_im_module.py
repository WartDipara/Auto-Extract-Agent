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
    assert parse_task_message('{"get-texts":{"urls":[]}}') is None


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


def test_find_by_source():
    from queue_reader import find_by_source

    status = {
        "active": [{"source_file": "im_1.json", "status": "preparing"}],
        "recent_done": [{"source_file": "im_2.json", "status": "success"}],
    }
    a, d = find_by_source(status, "im_1.json")
    assert a["status"] == "preparing" and d is None
    a, d = find_by_source(status, "im_2.json")
    assert a is None and d["status"] == "success"


def test_create_channel_routes(monkeypatch):
    from channels.factory import create_channel

    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "sec")
    ch = create_channel("feishu")
    assert ch.__class__.__name__ == "FeishuChannel"
    try:
        create_channel("dingtalk")
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert "dingtalk" in str(exc).lower() or "reserved" in str(exc).lower()
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
        for name in ("config", "queue_manager"):
            sys.modules.pop(name, None)

    import config
    import queue_manager as qm

    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "QUEUE_STATUS_FILE", tmp_path / "queue_status.json")
    monkeypatch.setattr(config, "BUF_DONE_DIR", tmp_path / "buf_done")
    monkeypatch.setattr(config, "QUEUE_RECENT_DONE_MAX", 10)
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
    assert qm.get_task(created[0].task_id) is None
    snap = json.loads(config.QUEUE_STATUS_FILE.read_text(encoding="utf-8"))
    assert snap["active"] == []
    assert snap["recent_done"][0]["status"] == "success"
    assert snap["recent_done"][0]["buf_done_zip"].endswith("stem_label.bin")
