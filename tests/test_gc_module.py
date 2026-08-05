"""Unit tests for apps/gc-module (no live IM / Module A)."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_GC_SRC = _ROOT / "apps" / "gc-module" / "src"

_GC_MODULE_NAMES = (
    "config",
    "main",
    "collector",
    "recheck",
    "sweeper",
    "eligibility",
    "audit",
    "lockfile",
    "models",
)


def _prefer_gc_path() -> None:
    gc = str(_GC_SRC)
    root = str(_ROOT)
    for p in (gc, root):
        while p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, root)
    sys.path.insert(0, gc)


def _purge_gc_modules():
    for name in _GC_MODULE_NAMES:
        sys.modules.pop(name, None)


@pytest.fixture()
def gc_env(tmp_path, monkeypatch, request):
    _prefer_gc_path()
    _purge_gc_modules()
    workspace = tmp_path / "workspace"
    result = tmp_path / "result"
    buf = tmp_path / "buf_done"
    downloads = tmp_path / "downloads"
    state = tmp_path / "gc_state"
    for d in (workspace, result, buf, downloads, state):
        d.mkdir()
    db = tmp_path / "tasks.db"
    _init_db(db)

    _prefer_gc_path()
    _purge_gc_modules()
    import config

    assert "gc-module" in (config.__file__ or "").replace("\\", "/")

    monkeypatch.setattr(config, "TASKS_DB", db.resolve())
    monkeypatch.setattr(config, "WORKSPACE_ROOT", workspace.resolve())
    monkeypatch.setattr(config, "RESULT_DIR", result.resolve())
    monkeypatch.setattr(config, "BUF_DONE_DIR", buf.resolve())
    monkeypatch.setattr(config, "DOWNLOADS_DIR", downloads.resolve())
    monkeypatch.setattr(config, "STATE_DIR", state.resolve())
    monkeypatch.setattr(config, "LOCK_PATH", state.resolve() / "gc.lock")
    monkeypatch.setattr(config, "AUDIT_PATH", state.resolve() / "gc_audit.jsonl")
    monkeypatch.setattr(config, "RETENTION_DAYS", 7.0)
    monkeypatch.setattr(config, "RETENTION_SEC", 7.0 * 86400.0)
    monkeypatch.setattr(config, "DRY_RUN_ENV", False)

    def _cleanup() -> None:
        _purge_gc_modules()
        gc = str(_GC_SRC)
        while gc in sys.path:
            sys.path.remove(gc)

    request.addfinalizer(_cleanup)

    return {
        "db": db,
        "workspace": workspace,
        "result": result,
        "buf": buf,
        "downloads": downloads,
        "state": state,
        "config": config,
    }


def _init_db(db: Path) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            url TEXT, label TEXT, filename TEXT, status TEXT, error TEXT,
            result_csv TEXT, session_id TEXT, buf_done_zip TEXT, source_file TEXT,
            adb_serial TEXT, created_at TEXT, updated_at TEXT, finished_at TEXT,
            im_delivered_at TEXT, im_chat_id TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _insert(db: Path, **fields) -> None:
    cols = [
        "task_id",
        "url",
        "label",
        "filename",
        "status",
        "error",
        "result_csv",
        "session_id",
        "buf_done_zip",
        "source_file",
        "adb_serial",
        "created_at",
        "updated_at",
        "finished_at",
        "im_delivered_at",
        "im_chat_id",
    ]
    values = {c: "" for c in cols}
    values.update(fields)
    conn = sqlite3.connect(str(db))
    conn.execute(
        f"INSERT INTO tasks ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        [values[c] for c in cols],
    )
    conn.commit()
    conn.close()


def _touch_trio(env, task_id: str, stem: str = "pack") -> dict[str, Path]:
    ws = env["workspace"] / task_id
    ws.mkdir(parents=True)
    (ws / "outputs").mkdir()
    (ws / "outputs" / "tests.csv").write_text("x\n", encoding="utf-8")
    csv = env["result"] / f"{stem}_game.csv"
    csv.write_text("hello\n", encoding="utf-8")
    trad = env["result"] / f"{stem}_game_T.csv"
    trad.write_text("hello_t\n", encoding="utf-8")
    bin_path = env["buf"] / f"{stem}_game.bin"
    bin_path.write_bytes(b"PK\x03\x04")
    return {"workspace": ws, "csv": csv, "trad": trad, "bin": bin_path}


def test_eligibility_awaiting_im(gc_env):
    from eligibility import row_eligible

    ok, why = row_eligible(
        {
            "status": "success",
            "im_chat_id": "group:cid",
            "im_delivered_at": "",
            "finished_at": "2020-01-01T00:00:00Z",
        }
    )
    assert ok is False
    assert why == "awaiting_im_delivery"


def test_eligibility_delivered_too_young(gc_env):
    from eligibility import row_eligible

    now = time.time()
    recent = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))
    ok, why = row_eligible(
        {
            "status": "success",
            "im_chat_id": "group:cid",
            "im_delivered_at": recent,
            "finished_at": recent,
        },
        now=now,
    )
    assert ok is False
    assert why == "delivered_too_young"


def test_eligibility_delivered_aged(gc_env):
    from eligibility import row_eligible

    now = time.time()
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 8 * 86400))
    ok, why = row_eligible(
        {
            "status": "success",
            "im_chat_id": "group:cid",
            "im_delivered_at": old,
            "finished_at": old,
        },
        now=now,
    )
    assert ok is True
    assert why == "delivered"


def test_eligibility_no_im_chat(gc_env):
    from eligibility import row_eligible

    now = time.time()
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 8 * 86400))
    ok, why = row_eligible(
        {
            "status": "failed",
            "im_chat_id": "",
            "im_delivered_at": "",
            "finished_at": old,
        },
        now=now,
    )
    assert ok is True
    assert why == "no_im_chat"


def test_sweep_deletes_trio_when_delivered_aged(gc_env):
    env = gc_env
    paths = _touch_trio(env, "t-aged")
    now = time.time()
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 8 * 86400))
    _insert(
        env["db"],
        task_id="t-aged",
        status="success",
        im_chat_id="group:cid",
        im_delivered_at=old,
        finished_at=old,
        result_csv=str(paths["csv"]),
        buf_done_zip=str(paths["bin"]),
        filename="a.apk",
    )

    from main import run_once

    summary = run_once(dry_run=False)
    assert summary["passed"] >= 1
    assert not paths["workspace"].exists()
    assert not paths["csv"].exists()
    assert not paths["trad"].exists()
    assert not paths["bin"].exists()


def test_missing_member_still_deletes_others(gc_env):
    env = gc_env
    paths = _touch_trio(env, "t-partial")
    paths["bin"].unlink()  # b gone
    now = time.time()
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 8 * 86400))
    _insert(
        env["db"],
        task_id="t-partial",
        status="success",
        im_chat_id="group:cid",
        im_delivered_at=old,
        finished_at=old,
        result_csv=str(paths["csv"]),
        buf_done_zip=str(paths["bin"]),
    )

    from main import run_once

    run_once(dry_run=False)
    assert not paths["workspace"].exists()
    assert not paths["csv"].exists()
    assert not paths["trad"].exists()


def test_undelivered_with_chat_not_deleted(gc_env):
    env = gc_env
    paths = _touch_trio(env, "t-pending")
    old = "2020-01-01T00:00:00Z"
    _insert(
        env["db"],
        task_id="t-pending",
        status="success",
        im_chat_id="group:cid",
        im_delivered_at="",
        finished_at=old,
        result_csv=str(paths["csv"]),
        buf_done_zip=str(paths["bin"]),
    )

    from main import run_once

    run_once(dry_run=False)
    assert paths["workspace"].exists()
    assert paths["csv"].exists()
    assert paths["bin"].exists()


def test_recheck_drops_if_delivery_cleared(gc_env):
    env = gc_env
    paths = _touch_trio(env, "t-race")
    now = time.time()
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 8 * 86400))
    _insert(
        env["db"],
        task_id="t-race",
        status="success",
        im_chat_id="group:cid",
        im_delivered_at=old,
        finished_at=old,
        result_csv=str(paths["csv"]),
        buf_done_zip=str(paths["bin"]),
    )

    from collector import collect_candidates
    from recheck import recheck_candidates

    marked = collect_candidates(now=now)
    assert any(g.task_id == "t-race" for g in marked)

    conn = sqlite3.connect(str(env["db"]))
    conn.execute(
        "UPDATE tasks SET im_delivered_at='' WHERE task_id=?", ("t-race",)
    )
    conn.commit()
    conn.close()

    passed, dropped = recheck_candidates(marked, now=now)
    assert not any(g.task_id == "t-race" for g in passed)
    assert any(t == "t-race" and r == "awaiting_im_delivery" for t, r in dropped)
    assert paths["workspace"].exists()


def test_permission_error_soft_fail(gc_env):
    env = gc_env
    paths = _touch_trio(env, "t-lock")
    now = time.time()
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 8 * 86400))
    _insert(
        env["db"],
        task_id="t-lock",
        status="success",
        im_chat_id="group:cid",
        im_delivered_at=old,
        finished_at=old,
        result_csv=str(paths["csv"]),
        buf_done_zip=str(paths["bin"]),
    )

    from sweeper import sweep_group
    from collector import collect_candidates
    from recheck import recheck_candidates

    marked = collect_candidates(now=now)
    passed, _ = recheck_candidates(marked, now=now)
    group = next(g for g in passed if g.task_id == "t-lock")

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self == paths["bin"]:
            raise PermissionError("locked")
        return real_unlink(self, *args, **kwargs)

    with patch.object(Path, "unlink", flaky_unlink):
        results = sweep_group(group, dry_run=False)

    statuses = {r["path"]: r["status"] for r in results}
    assert statuses[str(paths["bin"])] == "skipped"
    # workspace uses rmtree — still deleted; csv deleted
    assert not paths["csv"].exists()
    assert paths["bin"].exists()


def test_active_with_stop_not_deleted(gc_env):
    env = gc_env
    ws = env["workspace"] / "t-active"
    ws.mkdir(parents=True)
    (ws / ".stop").write_text("", encoding="utf-8")
    (ws / "keep.txt").write_text("x", encoding="utf-8")
    _insert(
        env["db"],
        task_id="t-active",
        status="on_extract",
        im_chat_id="group:cid",
        im_delivered_at="",
        finished_at="",
    )

    from main import run_once

    run_once(dry_run=False)
    assert ws.exists()
    assert (ws / "keep.txt").exists()


def test_lock_second_instance(gc_env):
    from lockfile import acquire_lock, release_lock

    assert acquire_lock() is True
    # Same pid can take over after rewrite; simulate other pid.
    lock = gc_env["state"] / "gc.lock"
    lock.write_text("1", encoding="utf-8")  # pid 1 usually exists on Unix; on Windows may not

    with patch("lockfile._pid_alive", return_value=True):
        from lockfile import acquire_lock as acquire2

        # Re-import path: call module function with patched alive
        import lockfile as lf

        assert lf.acquire_lock() is False
    release_lock()


def test_dry_run_keeps_files(gc_env):
    env = gc_env
    paths = _touch_trio(env, "t-dry")
    now = time.time()
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 8 * 86400))
    _insert(
        env["db"],
        task_id="t-dry",
        status="success",
        im_chat_id="group:cid",
        im_delivered_at=old,
        finished_at=old,
        result_csv=str(paths["csv"]),
        buf_done_zip=str(paths["bin"]),
    )

    from main import run_once

    summary = run_once(dry_run=True)
    assert summary["passed"] >= 1
    assert paths["workspace"].exists()
    assert paths["bin"].exists()
    assert all(r["status"] == "dry_run" for r in summary["results"] if r["task_id"] == "t-dry")
