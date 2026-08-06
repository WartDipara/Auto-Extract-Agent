"""Core inbox accept / source_file idempotency."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_A_SRC = _ROOT / "apps" / "auto-extract" / "src"
_A_APP = _ROOT / "apps" / "auto-extract"


def _load_auto_extract():
    # Prefer auto-extract on path; drop conflicting IM config/courier.
    for p in (str(_A_APP), str(_A_SRC), str(_ROOT)):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in list(sys.modules):
        if name in {
            "config",
            "router",
            "queue_manager",
            "task_store",
            "inbox_watcher",
            "pipeline",
            "handlers",
            "handlers.get_texts",
        } or name.startswith("handlers."):
            sys.modules.pop(name, None)


def test_dispatch_rejects_unknown_and_empty_urls(tmp_path, monkeypatch):
    _load_auto_extract()
    import config
    import router
    import task_store
    import handlers.get_texts as gt

    monkeypatch.setattr(config, "TASKS_DB", tmp_path / "tasks.db")
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(config, "QUEUE_STATUS_FILE", tmp_path / "state" / "q.json")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    task_store.open_store()

    router.ROUTES.clear()
    router.register("get-texts", gt.handle_get_texts)
    monkeypatch.setattr(gt, "ensure_worker", lambda: None)

    src = tmp_path / "im_bad.json"
    src.write_text("{}", encoding="utf-8")
    assert router.dispatch({"nope": {"urls": ["https://a.apk"]}}, src) is False
    assert router.dispatch({"get-texts": {"urls": []}}, src) is False

    src2 = tmp_path / "im_ok.json"
    assert (
        router.dispatch(
            {"get-texts": {"urls": ["https://a.apk"], "im_chat_id": "group:x"}},
            src2,
        )
        is True
    )
    assert (
        router.dispatch(
            {
                "get-texts": {
                    "urls": ["https://a.apk"],
                    "im_chat_id": "group:x",
                }
            },
            src2,
        )
        is True
    )

    # Different inbox filename, same URL while still active → no second task.
    src3 = tmp_path / "im_dup.json"
    assert (
        router.dispatch(
            {
                "get-texts": {
                    "urls": ["https://a.apk"],
                    "im_chat_id": "group:x",
                }
            },
            src3,
        )
        is True
    )
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "tasks.db"))
    n = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE url=?", ("https://a.apk",)
    ).fetchone()[0]
    conn.close()
    assert n == 1


def test_watcher_moves_rejected_prefix(tmp_path, monkeypatch):
    _load_auto_extract()
    import config
    import inbox_watcher
    import router

    inbox = tmp_path / "inbox"
    processed = tmp_path / "processed"
    inbox.mkdir()
    processed.mkdir()
    monkeypatch.setattr(config, "INBOX_DIR", inbox)
    monkeypatch.setattr(config, "PROCESSED_DIR", processed)

    router.ROUTES.clear()

    def _reject(_body, _path):
        return False

    router.register("get-texts", _reject)
    bad = inbox / "im_x.json"
    bad.write_text(
        json.dumps({"get-texts": {"urls": []}}), encoding="utf-8"
    )
    monkeypatch.setattr(inbox_watcher, "_SETTLE_SEC", 0.0)
    inbox_watcher._process_file(bad)
    assert not bad.exists()
    assert (processed / "rejected_im_x.json").is_file()
