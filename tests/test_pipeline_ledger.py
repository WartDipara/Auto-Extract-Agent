from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_A_APP = _ROOT / "apps" / "auto-extract"
_A_SRC = _A_APP / "src"
_IM_SRC = _ROOT / "apps" / "im-module" / "src"
for p in (_A_SRC, _A_APP, _IM_SRC, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def test_task_store_persist_and_update(tmp_path, monkeypatch):
    import config
    import task_store

    db = tmp_path / "tasks.db"
    monkeypatch.setattr(config, "TASKS_DB", db)
    task_store._conn = None
    task_store.open_store()

    from models import Task

    t = Task(task_id="t-0001", url="https://x/a.apk", source_file="im_1.json")
    task_store.insert_task(t)
    got = task_store.get_task("t-0001")
    assert got is not None and got.status == "queued"

    updated = task_store.update_task("t-0001", status="downloaded", filename="a.apk")
    assert updated is not None and updated.status == "downloaded"
    assert updated.filename == "a.apk"

    again = task_store.get_task("t-0001")
    assert again is not None and again.status == "downloaded"


def test_recovery_matrix_routes(tmp_path, monkeypatch):
    # Ensure auto-extract config wins over im-module config on sys.path.
    for p in list(sys.path):
        if p.replace("\\", "/").endswith("im-module/src"):
            sys.path.remove(p)
    if str(_A_SRC) not in sys.path:
        sys.path.insert(0, str(_A_SRC))

    import importlib

    import config

    importlib.reload(config)
    import pipeline
    import pipeline_queues as pq
    import task_store
    from models import Task

    db = tmp_path / "tasks.db"
    monkeypatch.setattr(config, "TASKS_DB", db)
    monkeypatch.setattr(config, "DOWNLOADS_DIR", tmp_path / "dl")
    config.DOWNLOADS_DIR.mkdir()
    task_store._conn = None
    task_store.open_store()

    for q in (pq.Q_DOWNLOAD, pq.Q_PATCH, pq.Q_DEVICE, pq.Q_EXTRACT, pq.Q_ARCHIVE):
        while not q.empty():
            try:
                q.get_nowait()
                q.task_done()
            except Exception:
                break

    task_store.insert_task(
        Task(task_id="t-q", url="https://x/q.apk", source_file="a.json", status="queued")
    )
    apk = config.DOWNLOADS_DIR / "d.apk"
    apk.write_bytes(b"apk")
    task_store.insert_task(
        Task(
            task_id="t-d",
            url="https://x/d.apk",
            source_file="a.json",
            status="downloaded",
            filename="d.apk",
        )
    )
    task_store.insert_task(
        Task(
            task_id="t-od",
            url="https://x/od.apk",
            source_file="a.json",
            status="on_device",
        )
    )
    task_store.insert_task(
        Task(
            task_id="t-oe",
            url="https://x/oe.apk",
            source_file="a.json",
            status="on_extract",
        )
    )

    pipeline.recover_and_enqueue()
    time.sleep(0.05)

    assert task_store.get_task("t-od").status == "failed"
    assert task_store.get_task("t-oe").status == "failed"


def test_adb_pool_exclusive(monkeypatch):
    from resource_pools import AdbPool

    pool = AdbPool(wait_timeout_sec=1.0)
    monkeypatch.setattr(
        pool,
        "refresh",
        lambda: ["dev-a"],
    )
    # inject fake lock map
    import threading

    with pool._cond:
        pool._locks = {"dev-a": threading.Lock()}

    held = []

    def hold():
        s = pool.acquire()
        held.append(s)
        time.sleep(0.3)
        pool.release(s)

    t1 = threading.Thread(target=hold)
    t2 = threading.Thread(target=hold)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert held == ["dev-a", "dev-a"]


def test_ops_commands_parse():
    # Prefer im-module ops_commands
    if str(_A_SRC) in sys.path:
        sys.path.remove(str(_A_SRC))
    sys.path.insert(0, str(_IM_SRC))
    import importlib

    import ops_commands

    importlib.reload(ops_commands)
    assert ops_commands.parse_ops_command("query all").kind == "query_all"
    assert ops_commands.parse_ops_command("query top_n 20").arg == "20"
    assert ops_commands.parse_ops_command("query gid t-1").arg == "t-1"
    assert ops_commands.parse_ops_command("query status success").arg == "success"
    assert ops_commands.parse_ops_command("help").kind == "help"
    assert ops_commands.parse_ops_command("查询表格 all") is None
    assert ops_commands.parse_ops_command('{"get-texts":{"urls":["x"]}}') is None


def test_ledger_query_export(tmp_path, monkeypatch):
    if str(_A_SRC) in sys.path:
        sys.path.remove(str(_A_SRC))
    sys.path.insert(0, str(_IM_SRC))
    import importlib
    import sqlite3

    import config as im_config

    importlib.reload(im_config)
    db = tmp_path / "tasks.db"
    export = tmp_path / "exports"
    monkeypatch.setattr(im_config, "TASKS_DB", db)
    monkeypatch.setattr(im_config, "QUERY_EXPORT_DIR", export)

    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            url TEXT, label TEXT, filename TEXT, status TEXT, error TEXT,
            result_csv TEXT, session_id TEXT, buf_done_zip TEXT, source_file TEXT,
            adb_serial TEXT, created_at TEXT, updated_at TEXT, finished_at TEXT,
            im_delivered_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "t-0001",
            "https://x/a.apk",
            "Game",
            "a.apk",
            "success",
            "",
            "",
            "",
            "",
            "im_1.json",
            "",
            "2026-01-01",
            "2026-01-02",
            "2026-01-02",
            "",
        ),
    )
    conn.commit()
    conn.close()

    import ops_commands
    import task_ledger_query

    importlib.reload(ops_commands)
    importlib.reload(task_ledger_query)

    r = task_ledger_query.run_ledger_query(
        ops_commands.OpsCommand(kind="query_all")
    )
    assert r.ok and r.row_count == 1 and r.csv_path and r.csv_path.is_file()

    miss = task_ledger_query.run_ledger_query(
        ops_commands.OpsCommand(kind="query_gid", arg="nope")
    )
    assert miss.ok and miss.row_count == 0 and "not found" in miss.message
