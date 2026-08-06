"""Pipeline robustness: task_root isolation, start idempotency, recover isolation."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]
_A_APP = _ROOT / "apps" / "auto-extract"
_A_SRC = _A_APP / "src"
for p in (_A_SRC, _A_APP, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _purge_core_modules():
    for p in list(sys.path):
        if "im-module" in p.replace("\\", "/"):
            sys.path.remove(p)
    if str(_A_SRC) not in sys.path:
        sys.path.insert(0, str(_A_SRC))
    for name in list(sys.modules):
        if name in (
            "config",
            "task_store",
            "pipeline",
            "pipeline_queues",
            "extract_bridge",
            "inbox_watcher",
            "errors",
            "errors.sinks",
            "queue_manager",
            "models",
        ) or name.startswith("errors."):
            sys.modules.pop(name, None)


def test_wait_for_csv_uses_explicit_task_root_not_global(tmp_path, monkeypatch):
    _purge_core_modules()
    import extract_bridge as eb

    root_a = tmp_path / "task_a"
    root_b = tmp_path / "task_b"
    for root in (root_a, root_b):
        out = root / "outputs"
        out.mkdir(parents=True)
    (root_a / "outputs" / "tests.csv").write_text(
        "text\nfrom-a\n", encoding="utf-8-sig"
    )
    (root_b / "outputs" / "tests.csv").write_text(
        "text\nfrom-b\n", encoding="utf-8-sig"
    )

    # Pollute global with A while archive reads B.
    eb._task_root = root_a.resolve()
    path, text = eb.wait_for_csv("ignored.apk", timeout_sec=0.2, task_root=root_b)
    assert "from-b" in text
    assert path.resolve() == (root_b / "outputs" / "tests.csv").resolve()

    ensured = eb.ensure_csv_after_agent("x.apk", task_root=root_b)
    assert ensured.resolve() == path.resolve()


def test_start_pipeline_idempotent_after_recover_failure(tmp_path, monkeypatch):
    _purge_core_modules()
    import config
    import pipeline
    import pipeline_queues as pq

    monkeypatch.setattr(config, "DOWNLOAD_WORKERS", 1)
    monkeypatch.setattr(config, "PATCH_WORKERS", 1)
    monkeypatch.setattr(config, "OPENCODE_SLOTS", 1)
    monkeypatch.setattr(config, "HEARTBEAT_FILE", tmp_path / "hb")
    monkeypatch.setattr(pipeline, "ensure_buf_done_worker", lambda: None)

    class _Pool:
        def refresh(self):
            return ["serial-1"]

        def acquire(self, *_a, **_k):
            raise TimeoutError("unused")

        def release(self, *_a, **_k):
            pass

    monkeypatch.setattr(pipeline, "_pools", lambda: (_Pool(), _Pool()))
    calls = {"recover": 0, "threads": 0}
    real_thread = threading.Thread

    def _counting_thread(*args, **kwargs):
        calls["threads"] += 1
        return real_thread(*args, **kwargs)

    monkeypatch.setattr(pipeline.threading, "Thread", _counting_thread)

    def _boom_recover():
        calls["recover"] += 1
        raise RuntimeError("recover boom")

    monkeypatch.setattr(pipeline, "recover_and_enqueue", _boom_recover)

    # Drain queues so daemon workers do not see stale work.
    for q in (pq.Q_DOWNLOAD, pq.Q_PATCH, pq.Q_DEVICE, pq.Q_EXTRACT, pq.Q_ARCHIVE):
        while not q.empty():
            try:
                q.get_nowait()
                q.task_done()
            except Exception:
                break

    pipeline._started = False
    pipeline.start_pipeline()
    first_threads = calls["threads"]
    assert pipeline._started is True
    assert calls["recover"] == 1

    pipeline.start_pipeline()
    assert calls["threads"] == first_threads
    assert calls["recover"] == 1


def test_recover_isolates_per_task_failure(tmp_path, monkeypatch):
    _purge_core_modules()
    import config
    import pipeline
    import pipeline_queues as pq
    import task_store
    from models import Task

    db = tmp_path / "tasks.db"
    monkeypatch.setattr(config, "TASKS_DB", db)
    task_store._conn = None
    task_store.open_store()

    task_store.insert_task(
        Task(task_id="t-bad", url="https://x/bad.apk", status="queued")
    )
    task_store.insert_task(
        Task(task_id="t-ok", url="https://x/ok.apk", status="queued")
    )

    seen: list[str] = []

    def _put_download(task):
        if task.task_id == "t-bad":
            raise RuntimeError("poison task")
        seen.append(task.task_id)

    monkeypatch.setattr(pq, "put_download", _put_download)
    pipeline.recover_and_enqueue()
    assert seen == ["t-ok"]


def test_queue_sink_exception_does_not_raise(tmp_path, monkeypatch):
    _purge_core_modules()
    import config
    from errors.model import ErrorInfo
    from errors.sinks import QueueSink, emit, register_sink

    monkeypatch.setattr(config, "SERVICE_LOG", tmp_path / "service.log")

    class _BoomQM:
        @staticmethod
        def update_task(*_a, **_k):
            raise RuntimeError("db locked")

    import errors.sinks as sinks

    monkeypatch.setattr(sinks, "queue_manager", _BoomQM)
    # Fresh sink list for this test.
    sinks._SINKS.clear()
    register_sink(QueueSink())
    emit(
        ErrorInfo(code="X", message="m", stage="device", status="failed"),
        task_id="t-1",
    )
    assert (tmp_path / "service.log").is_file()


def test_inbox_poison_rejected_after_budget(tmp_path, monkeypatch):
    _purge_core_modules()
    import config
    import inbox_watcher as iw

    inbox = tmp_path / "inbox"
    processed = tmp_path / "processed"
    inbox.mkdir()
    monkeypatch.setattr(config, "INBOX_DIR", inbox)
    monkeypatch.setattr(config, "PROCESSED_DIR", processed)
    monkeypatch.setattr(config, "INBOX_PROCESS_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(iw, "_SETTLE_SEC", 0.0)
    iw._FAIL_COUNTS.clear()
    iw._PROCESSING.clear()

    poison = inbox / "poison.json"
    poison.write_text('{"urls":["https://x/a.apk"]}', encoding="utf-8")

    def _boom(_data, _path):
        raise RuntimeError("dispatch boom")

    monkeypatch.setattr(iw, "dispatch", _boom)
    iw._process_file(poison)
    assert poison.is_file()
    iw._process_file(poison)
    assert not poison.is_file()
    rejected = list(processed.glob("rejected_poison.json*"))
    assert rejected
