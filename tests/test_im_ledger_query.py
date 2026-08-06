"""Ledger query: mine vs progress, fuzzy gid."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_IM_SRC = _ROOT / "apps" / "im-module" / "src"
for p in (_IM_SRC, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _reload_im():
    for name in ("config", "ops_commands", "task_ledger_query"):
        sys.modules.pop(name, None)


def _seed_db(db: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            label TEXT, status TEXT, error TEXT, url TEXT, filename TEXT,
            updated_at TEXT, im_delivered_at TEXT, im_deliver_error TEXT,
            session_id TEXT, adb_serial TEXT, buf_done_zip TEXT,
            im_chat_id TEXT, im_sender_id TEXT, finished_at TEXT
        )
        """
    )
    for row in rows:
        conn.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
    conn.commit()
    conn.close()


def test_query_mine_filters_sender(tmp_path, monkeypatch):
    _reload_im()
    import config
    from ops_commands import OpsCommand
    from task_ledger_query import run_ledger_query

    db = tmp_path / "tasks.db"
    monkeypatch.setattr(config, "TASKS_DB", db)
    _seed_db(
        db,
        [
            (
                "t-a",
                "gameA",
                "queued",
                "",
                "https://x/a.apk",
                "a.apk",
                "2026-01-02T00:00:00Z",
                "",
                "",
                "",
                "",
                "",
                "group:a",
                "staff-a",
                "",
            ),
            (
                "t-b",
                "gameB",
                "on_device",
                "",
                "https://x/b.apk",
                "b.apk",
                "2026-01-02T00:00:01Z",
                "",
                "",
                "",
                "",
                "",
                "group:a",
                "staff-b",
                "",
            ),
        ],
    )
    mine = run_ledger_query(OpsCommand(kind="query_mine"), sender_id="staff-a")
    assert mine.ok
    assert "t-a" in mine.message
    assert "t-b" not in mine.message
    assert "mine:" in mine.message

    all_prog = run_ledger_query(OpsCommand(kind="query_progress"))
    assert all_prog.ok
    assert "t-a" in all_prog.message
    assert "t-b" in all_prog.message


def test_query_mine_requires_sender(tmp_path, monkeypatch):
    _reload_im()
    import config
    from ops_commands import OpsCommand
    from task_ledger_query import run_ledger_query

    db = tmp_path / "tasks.db"
    monkeypatch.setattr(config, "TASKS_DB", db)
    _seed_db(db, [])
    result = run_ledger_query(OpsCommand(kind="query_mine"), sender_id="")
    assert not result.ok
    assert "提问人" in result.message


def test_query_gid_fuzzy_multi(tmp_path, monkeypatch):
    _reload_im()
    import config
    from ops_commands import OpsCommand
    from task_ledger_query import run_ledger_query

    db = tmp_path / "tasks.db"
    monkeypatch.setattr(config, "TASKS_DB", db)
    _seed_db(
        db,
        [
            (
                "t-1",
                "foo_game",
                "success",
                "",
                "https://cdn.example.com/a.apk",
                "a.apk",
                "2026-01-02T00:00:02Z",
                "d",
                "",
                "",
                "",
                "",
                "group:a",
                "s1",
                "",
            ),
            (
                "t-2",
                "foo_other",
                "failed",
                "boom",
                "https://cdn.example.com/b.apk",
                "b.apk",
                "2026-01-02T00:00:01Z",
                "",
                "send fail",
                "",
                "",
                "",
                "group:a",
                "s2",
                "",
            ),
            (
                "t-3",
                "bar_game",
                "queued",
                "",
                "https://cdn.example.com/c.apk",
                "c.apk",
                "2026-01-02T00:00:00Z",
                "",
                "",
                "",
                "",
                "",
                "group:a",
                "s3",
                "",
            ),
        ],
    )
    result = run_ledger_query(OpsCommand(kind="query_label", arg="foo"))
    assert result.ok
    assert result.row_count == 2
    assert "t-1" in result.message
    assert "t-2" in result.message
    assert "t-3" not in result.message
    assert "deliver_err" in result.message

    by_label = run_ledger_query(OpsCommand(kind="query_label", arg="bar"))
    assert by_label.ok and by_label.row_count == 1
    assert "t-3" in by_label.message

    # task_id must not be found via query label
    wrong = run_ledger_query(OpsCommand(kind="query_label", arg="t-3"))
    assert wrong.ok and wrong.row_count == 0

    exact = run_ledger_query(OpsCommand(kind="query_gid", arg="t-3"))
    assert exact.ok and exact.row_count == 1
    assert "t-3" in exact.message

    # label token must not be found via query gid
    no_gid = run_ledger_query(OpsCommand(kind="query_gid", arg="foo"))
    assert no_gid.ok and no_gid.row_count == 0


def test_parse_ops_query_mine():
    _reload_im()
    from ops_commands import parse_ops_command

    cmd = parse_ops_command("query mine")
    assert cmd is not None
    assert cmd.kind == "query_mine"
