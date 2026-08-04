from __future__ import annotations

import csv
import datetime as dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import config
from ops_commands import LEDGER_STATUSES, OpsCommand, is_valid_ledger_status

_EXPORT_COLS = (
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
)

_ALL_HARD_CAP = 50000


@dataclass
class LedgerQueryResult:
    ok: bool
    message: str
    csv_path: Path | None = None
    row_count: int = 0
    truncated: bool = False


def _connect() -> sqlite3.Connection:
    db = Path(config.TASKS_DB)
    if not db.is_file():
        raise FileNotFoundError(f"tasks db missing: {db}")
    uri = f"file:{db.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _write_csv(rows: list[sqlite3.Row], mode: str) -> Path:
    out_dir = Path(config.QUERY_EXPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"tasks_{mode}_{stamp}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=_EXPORT_COLS)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row[c] if c in row.keys() else "" for c in _EXPORT_COLS})
    return path


def run_ledger_query(cmd: OpsCommand) -> LedgerQueryResult:
    if cmd.kind == "help":
        return LedgerQueryResult(ok=False, message=config.OPS_TEMPLATE)

    if cmd.kind == "query_top_n":
        try:
            n = int((cmd.arg or "").strip())
        except ValueError:
            return LedgerQueryResult(
                ok=False,
                message=f"top_n requires an integer.\n{config.OPS_TEMPLATE}",
            )
        if n < 1 or n > 1000:
            return LedgerQueryResult(
                ok=False,
                message=f"top_n must be 1–1000.\n{config.OPS_TEMPLATE}",
            )
        sql = (
            f"SELECT {', '.join(_EXPORT_COLS)} FROM tasks "
            "ORDER BY updated_at DESC LIMIT ?"
        )
        params: tuple = (n,)
        mode = f"top_{n}"
    elif cmd.kind == "query_status":
        status = (cmd.arg or "").strip()
        if not is_valid_ledger_status(status):
            allowed = ", ".join(sorted(LEDGER_STATUSES))
            return LedgerQueryResult(
                ok=False,
                message=f"invalid status. allowed: {allowed}\n{config.OPS_TEMPLATE}",
            )
        sql = (
            f"SELECT {', '.join(_EXPORT_COLS)} FROM tasks "
            "WHERE status=? ORDER BY updated_at DESC"
        )
        params = (status,)
        mode = f"status_{status}"
    elif cmd.kind == "query_gid":
        gid = (cmd.arg or "").strip()
        if not gid:
            return LedgerQueryResult(
                ok=False,
                message=f"gid is required.\n{config.OPS_TEMPLATE}",
            )
        sql = (
            f"SELECT {', '.join(_EXPORT_COLS)} FROM tasks "
            "WHERE task_id=? OR filename=? OR url=? "
            "ORDER BY updated_at DESC"
        )
        params = (gid, gid, gid)
        mode = "gid"
    elif cmd.kind == "query_all":
        sql = (
            f"SELECT {', '.join(_EXPORT_COLS)} FROM tasks "
            "ORDER BY updated_at DESC LIMIT ?"
        )
        params = (_ALL_HARD_CAP + 1,)
        mode = "all"
    else:
        return LedgerQueryResult(ok=False, message=config.OPS_TEMPLATE)

    try:
        conn = _connect()
    except FileNotFoundError as exc:
        return LedgerQueryResult(ok=False, message=str(exc))

    try:
        rows = list(conn.execute(sql, params).fetchall())
    finally:
        conn.close()

    if cmd.kind == "query_gid" and not rows:
        return LedgerQueryResult(ok=True, message=f"not found: {cmd.arg}", row_count=0)

    truncated = False
    if cmd.kind == "query_all" and len(rows) > _ALL_HARD_CAP:
        rows = rows[:_ALL_HARD_CAP]
        truncated = True

    path = _write_csv(rows, mode)
    msg = f"exported {len(rows)} rows"
    if truncated:
        msg += " truncated=true"
    return LedgerQueryResult(
        ok=True,
        message=msg,
        csv_path=path,
        row_count=len(rows),
        truncated=truncated,
    )
