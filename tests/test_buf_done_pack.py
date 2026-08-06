"""Tests for buf_done encrypted result packing (.zip)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pyzipper

_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "apps" / "auto-extract"
_SRC = _APP / "src"
_TEST_PASSWORD = "gametool999"


def _ensure_auto_extract_imports() -> None:
    """Prefer auto-extract modules over im-module when tests share one process."""
    for p in (str(_SRC), str(_APP)):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    cfg = sys.modules.get("config")
    if cfg is not None and "auto-extract" not in (cfg.__file__ or ""):
        for name in ("config", "buf_done", "queue_manager"):
            sys.modules.pop(name, None)


def _set_password(monkeypatch, password: str = _TEST_PASSWORD):
    _ensure_auto_extract_imports()
    import config

    monkeypatch.setattr(config, "ZIP_PASSWORD", password)


def test_pack_single_csv(tmp_path, monkeypatch):
    _set_password(monkeypatch)
    from buf_done import pack_result_zip

    primary = tmp_path / "demo_纯简.csv"
    primary.write_text("你好\n", encoding="utf-8-sig")
    out = tmp_path / "buf_done"
    zip_path = pack_result_zip(primary, out_dir=out)
    assert zip_path == out / "demo_纯简.zip"
    assert primary.is_file()
    with pyzipper.AESZipFile(zip_path, "r") as zf:
        zf.setpassword(_TEST_PASSWORD.encode("utf-8"))
        assert zf.namelist() == ["demo_纯简.csv"]
        assert zf.read("demo_纯简.csv") == primary.read_bytes()


def test_pack_dual_csv_includes_t(tmp_path, monkeypatch):
    _set_password(monkeypatch)
    from buf_done import collect_result_csvs, pack_result_zip

    primary = tmp_path / "demo_混用.csv"
    trad = tmp_path / "demo_混用_T.csv"
    primary.write_text("简体\n", encoding="utf-8-sig")
    trad.write_text("繁體\n", encoding="utf-8-sig")
    assert [p.name for p in collect_result_csvs(primary)] == [
        "demo_混用.csv",
        "demo_混用_T.csv",
    ]
    zip_path = pack_result_zip(primary, out_dir=tmp_path / "buf_done")
    with pyzipper.AESZipFile(zip_path, "r") as zf:
        zf.setpassword(_TEST_PASSWORD.encode("utf-8"))
        assert sorted(zf.namelist()) == ["demo_混用.csv", "demo_混用_T.csv"]
    assert primary.is_file() and trad.is_file()


def test_pack_requires_zip_password(tmp_path, monkeypatch):
    _set_password(monkeypatch, "")
    from buf_done import pack_result_zip

    primary = tmp_path / "demo.csv"
    primary.write_text("x\n", encoding="utf-8")
    try:
        pack_result_zip(primary, out_dir=tmp_path / "buf_done")
        raised = False
    except RuntimeError as exc:
        raised = True
        assert "ZIP_PASSWORD" in str(exc)
    assert raised


def test_enqueue_does_not_block(tmp_path, monkeypatch):
    _set_password(monkeypatch)
    import buf_done
    import config

    monkeypatch.setattr(config, "BUF_DONE_DIR", tmp_path / "buf_done")

    # Reset worker so this test owns the queue/thread.
    buf_done._worker_started = False
    primary = tmp_path / "demo_异步.csv"
    primary.write_text("行\n", encoding="utf-8-sig")
    buf_done.enqueue_buf_done(primary)
    zip_path = tmp_path / "buf_done" / "demo_异步.zip"
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not zip_path.is_file():
        time.sleep(0.05)
    assert zip_path.is_file()
    with pyzipper.AESZipFile(zip_path, "r") as zf:
        zf.setpassword(_TEST_PASSWORD.encode("utf-8"))
        assert zf.namelist() == ["demo_异步.csv"]


def test_pack_failure_marks_success_failed(tmp_path, monkeypatch):
    _set_password(monkeypatch)
    import buf_done
    import config
    from models import Task

    monkeypatch.setattr(config, "BUF_DONE_DIR", tmp_path / "buf_done")
    buf_done._worker_started = False
    task = Task(task_id="t-pack", url="https://x/a.apk", status="success")
    updates: list[dict] = []

    def _get_task(task_id: str):
        return task if task_id == "t-pack" else None

    def _update_task(task_id: str, **fields):
        updates.append(dict(fields))
        for key, value in fields.items():
            setattr(task, key, value)
        return task

    monkeypatch.setattr(buf_done.queue_manager, "get_task", _get_task)
    monkeypatch.setattr(buf_done.queue_manager, "update_task", _update_task)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(buf_done, "pack_result_zip", _boom)
    primary = tmp_path / "pack_fail.csv"
    primary.write_text("x\n", encoding="utf-8")
    buf_done.enqueue_buf_done(primary, task_id="t-pack")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and task.status == "success":
        time.sleep(0.05)
    assert task.status == "failed"
    assert updates and "BUF_DONE_PACK" in str(updates[0].get("error", ""))


def test_pack_failure_skips_non_success(tmp_path, monkeypatch):
    _set_password(monkeypatch)
    import buf_done
    import config
    from models import Task

    monkeypatch.setattr(config, "BUF_DONE_DIR", tmp_path / "buf_done")
    buf_done._worker_started = False
    task = Task(task_id="t-miss", url="https://x/a.apk", status="assets_missing")
    touched = []

    monkeypatch.setattr(
        buf_done.queue_manager,
        "get_task",
        lambda task_id: task if task_id == "t-miss" else None,
    )
    monkeypatch.setattr(
        buf_done.queue_manager,
        "update_task",
        lambda *a, **k: touched.append(k) or task,
    )
    monkeypatch.setattr(
        buf_done,
        "pack_result_zip",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("disk full")),
    )
    primary = tmp_path / "pack_skip.csv"
    primary.write_text("x\n", encoding="utf-8")
    buf_done.enqueue_buf_done(primary, task_id="t-miss")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and buf_done._job_queue.unfinished_tasks:
        time.sleep(0.05)
    assert task.status == "assets_missing"
    assert not touched


if __name__ == "__main__":
    import tempfile

    class _DummyMonkey:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    monkey = _DummyMonkey()
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        test_pack_single_csv(p, monkey)
        test_pack_dual_csv_includes_t(p, monkey)
        test_pack_requires_zip_password(p, monkey)
    print("BUF_DONE_PACK_OK")
