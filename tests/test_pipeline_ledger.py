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
    for p in list(sys.path):
        if "im-module" in p.replace("\\", "/"):
            sys.path.remove(p)
    if str(_A_SRC) not in sys.path:
        sys.path.insert(0, str(_A_SRC))
    for name in ("config", "task_store", "models"):
        sys.modules.pop(name, None)

    import config
    import task_store

    db = tmp_path / "tasks.db"
    monkeypatch.setattr(config, "TASKS_DB", db)
    task_store._conn = None
    task_store.open_store()

    from models import Task

    t = Task(
        task_id="t-0001",
        url="https://x/a.apk",
        source_file="im_1.json",
        im_chat_id="group:cid-a",
    )
    task_store.insert_task(t)
    got = task_store.get_task("t-0001")
    assert got is not None and got.status == "queued"
    assert got.im_chat_id == "group:cid-a"

    updated = task_store.update_task("t-0001", status="downloaded", filename="a.apk")
    assert updated is not None and updated.status == "downloaded"
    assert updated.filename == "a.apk"
    assert updated.im_chat_id == "group:cid-a"

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

    for name in (
        "config",
        "task_store",
        "queue_manager",
        "pipeline",
        "pipeline_queues",
        "models",
    ):
        sys.modules.pop(name, None)

    import config
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
    assert ops_commands.parse_ops_command("query progress").kind == "query_progress"
    assert ops_commands.parse_ops_command("query export").kind == "query_export"
    assert ops_commands.parse_ops_command("query password").kind == "query_password"
    assert ops_commands.parse_ops_command("query gid t-1").arg == "t-1"
    assert ops_commands.parse_ops_command("query status success").arg == "success"
    assert ops_commands.parse_ops_command("help").kind == "help"
    assert ops_commands.parse_ops_command("你好").kind == "greet"
    assert ops_commands.parse_ops_command("你好呀！").kind == "greet"
    assert ops_commands.parse_ops_command("Hello").kind == "greet"
    assert ops_commands.parse_ops_command("query all").kind == "help"
    assert ops_commands.parse_ops_command("query top_n 20").kind == "help"
    assert ops_commands.parse_ops_command("查询表格 all") is None
    assert ops_commands.parse_ops_command('{"get-texts":{"urls":["x"]}}') is None


def test_ledger_query_text(tmp_path, monkeypatch):
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
    monkeypatch.setattr(im_config, "ZIP_PASSWORD", "gametool999")

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
    conn.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "t-0001",
            "https://x/a.apk",
            "Game",
            "a.apk",
            "success",
            "",
            "",
            "ses-1",
            str(tmp_path / "a.bin"),
            "im_1.json",
            "emulator-5554",
            "2026-08-04T12:01:00Z",
            "2026-08-04T12:01:00Z",
            "2026-08-04T12:01:00Z",
            "2026-08-04T12:05:00Z",
            "group:cid-a",
        ),
    )
    (tmp_path / "a.bin").write_bytes(b"x")
    conn.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "t-0002",
            "https://x/b.apk",
            "ActiveGame",
            "b.apk",
            "on_extract",
            "",
            "",
            "",
            "",
            "im_1.json",
            "",
            "2026-08-04T12:00:00Z",
            "2026-08-04T12:00:30Z",
            "",
            "",
            "group:cid-a",
        ),
    )
    conn.commit()
    conn.close()

    import ops_commands
    import task_ledger_query

    importlib.reload(ops_commands)
    importlib.reload(task_ledger_query)

    assert task_ledger_query.to_shanghai("2026-08-04T12:01:00Z") == "2026-08-04 20:01:00"

    pw = task_ledger_query.run_ledger_query(
        ops_commands.OpsCommand(kind="query_password")
    )
    assert pw.ok and pw.message == "password is 'gametool999' , 将bin文件用zip解压"

    prog = task_ledger_query.run_ledger_query(
        ops_commands.OpsCommand(kind="query_progress")
    )
    assert prog.ok and "progress:" in prog.message and "t-0002" in prog.message
    assert "t-0001" not in prog.message
    assert prog.file_path is None

    gid = task_ledger_query.run_ledger_query(
        ops_commands.OpsCommand(kind="query_gid", arg="t-0001")
    )
    assert gid.ok and "2026-08-04 20:01:00" in gid.message
    assert "delivered  2026-08-04 20:05:00" in gid.message
    assert "buf_done   yes" in gid.message
    assert "session    ses-1" in gid.message
    assert "adb        emulator-5554" in gid.message

    exported = task_ledger_query.run_ledger_query(
        ops_commands.OpsCommand(kind="query_export")
    )
    assert exported.ok and exported.file_path and exported.file_path.is_file()
    assert exported.file_path.suffix == ".xlsx"
    assert exported.row_count == 2
    assert "export 2 rows xlsx" in exported.message
    from openpyxl import load_workbook

    wb = load_workbook(exported.file_path, read_only=True)
    sheet_rows = list(wb.active.iter_rows(values_only=True))
    assert sheet_rows[0][0] == "task_id"
    assert any(r[0] == "t-0001" for r in sheet_rows[1:])

    miss = task_ledger_query.run_ledger_query(
        ops_commands.OpsCommand(kind="query_gid", arg="nope")
    )
    assert miss.ok and miss.row_count == 0 and "not found" in miss.message