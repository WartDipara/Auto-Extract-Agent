from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import Workbook

import config
from ops_commands import (
    ACTIVE_STATUSES,
    LEDGER_STATUSES,
    OpsCommand,
    TERMINAL_STATUSES,
    is_valid_ledger_status,
)

_DISPLAY_COLS = ("task_id", "label", "status", "error", "updated_at")
_GID_COLS = (
    "task_id",
    "label",
    "status",
    "error",
    "updated_at",
    "im_delivered_at",
    "session_id",
    "adb_serial",
    "buf_done_zip",
)
_EXPORT_COLS = (
    "task_id",
    "label",
    "status",
    "error",
    "url",
    "filename",
    "im_chat_id",
    "session_id",
    "adb_serial",
    "im_delivered_at",
    "updated_at",
    "finished_at",
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CHAR_BUDGET = 3500
_LIST_ROW_CAP = 20
_PROGRESS_ROW_CAP = 30
_EXPORT_HARD_CAP = 50000
_LABEL_MAX = 20
_LIST_ERROR_MAX = 80
_GID_ERROR_MAX = 200


@dataclass
class LedgerQueryResult:
    ok: bool
    message: str
    file_path: Path | None = None
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


def to_shanghai(iso_utc: str) -> str:
    """UTC ISO (…Z or offset) → Asia/Shanghai wall time for chat display."""
    raw = (iso_utc or "").strip()
    if not raw:
        return "-"
    try:
        normalized = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        parsed = dt.datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def _clip(text: str, max_len: int) -> str:
    s = " ".join((text or "").split())
    if len(s) <= max_len:
        return s
    if max_len <= 1:
        return s[:max_len]
    return s[: max_len - 1] + "…"


def _is_failure_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES and status != "success"


def _format_progress(rows: list[sqlite3.Row], total: int) -> str:
    lines = [f"progress: {total} active"]
    for row in rows:
        label = _clip(str(row["label"] or "-"), _LABEL_MAX)
        lines.append(f"{row['task_id']}  {label}  {row['status']}")
    body = "\n".join(lines)
    if total > len(rows):
        body += (
            f"\n… showing {len(rows)}/{total}, "
            "use query gid <id> or query export"
        )
    return _fit_budget(body)


def _format_list(rows: list[sqlite3.Row], *, header: str, total: int) -> str:
    lines = [header]
    for row in rows:
        label = _clip(str(row["label"] or "-"), _LABEL_MAX)
        line = f"{row['task_id']}  {label}  {row['status']}"
        status = str(row["status"] or "")
        if _is_failure_terminal(status):
            err = _clip(str(row["error"] or ""), _LIST_ERROR_MAX)
            if err:
                line = f"{line}  {err}"
        lines.append(line)
    body = "\n".join(lines)
    if total > len(rows):
        body += (
            f"\n… showing {len(rows)}/{total}, "
            "use query gid <id> or query export"
        )
    return _fit_budget(body)


def _format_gid(rows: list[sqlite3.Row]) -> str:
    blocks: list[str] = []
    for row in rows:
        label = _clip(str(row["label"] or "-"), _LABEL_MAX)
        when = to_shanghai(str(row["updated_at"] or ""))
        head = f"{row['task_id']}  {label}  {row['status']}  {when}"
        bin_path = Path(str(row["buf_done_zip"] or "").strip())
        bin_flag = "yes" if bin_path.is_file() else "no"
        session = str(row["session_id"] or "").strip() or "-"
        adb = str(row["adb_serial"] or "").strip() or "-"
        lines = [
            head,
            f"delivered  {to_shanghai(str(row['im_delivered_at'] or ''))}",
            f"buf_done   {bin_flag}",
            f"session    {session}",
            f"adb        {adb}",
        ]
        err = _clip(str(row["error"] or ""), _GID_ERROR_MAX)
        if err:
            lines.append(err)
        blocks.append("\n".join(lines))
    return _fit_budget("\n\n".join(blocks))


def _fit_budget(text: str) -> str:
    if len(text) <= _CHAR_BUDGET:
        return text
    cut = text[: _CHAR_BUDGET - 20].rstrip()
    return cut + "\n… truncated"


def _write_export_xlsx(rows: list[sqlite3.Row]) -> Path:
    out_dir = Path(config.QUERY_EXPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(_SHANGHAI).strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"tasks_export_{stamp}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "tasks"
    ws.append(list(_EXPORT_COLS))
    for row in rows:
        ws.append([row[c] if c in row.keys() else "" for c in _EXPORT_COLS])
    wb.save(path)
    return path


def run_ledger_query(cmd: OpsCommand) -> LedgerQueryResult:
    if cmd.kind == "help":
        return LedgerQueryResult(ok=False, message=config.OPS_TEMPLATE)

    if cmd.kind == "query_password":
        password = (config.ZIP_PASSWORD or "").strip()
        if not password:
            return LedgerQueryResult(
                ok=False,
                message="ZIP_PASSWORD missing in apps/auto-extract/.env",
            )
        return LedgerQueryResult(
            ok=True,
            message=f"password is '{password}' , 将bin文件用zip解压",
        )

    try:
        conn = _connect()
    except FileNotFoundError as exc:
        return LedgerQueryResult(ok=False, message=str(exc))

    display_cols = ", ".join(_DISPLAY_COLS)
    gid_cols = ", ".join(_GID_COLS)
    export_cols = ", ".join(_EXPORT_COLS)
    try:
        if cmd.kind == "query_progress":
            placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
            statuses = tuple(sorted(ACTIVE_STATUSES))
            total = conn.execute(
                f"SELECT COUNT(*) FROM tasks WHERE status IN ({placeholders})",
                statuses,
            ).fetchone()[0]
            rows = list(
                conn.execute(
                    f"SELECT {display_cols} FROM tasks "
                    f"WHERE status IN ({placeholders}) "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (*statuses, _PROGRESS_ROW_CAP),
                ).fetchall()
            )
            return LedgerQueryResult(
                ok=True,
                message=_format_progress(rows, int(total)),
                row_count=len(rows),
                truncated=int(total) > len(rows),
            )

        if cmd.kind == "query_status":
            status = (cmd.arg or "").strip()
            if not is_valid_ledger_status(status):
                allowed = ", ".join(sorted(LEDGER_STATUSES))
                return LedgerQueryResult(
                    ok=False,
                    message=(
                        f"invalid status. allowed: {allowed}\n"
                        f"{config.OPS_TEMPLATE}"
                    ),
                )
            total = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status=?", (status,)
            ).fetchone()[0]
            rows = list(
                conn.execute(
                    f"SELECT {display_cols} FROM tasks WHERE status=? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (status, _LIST_ROW_CAP),
                ).fetchall()
            )
            return LedgerQueryResult(
                ok=True,
                message=_format_list(
                    rows,
                    header=f"status={status}  {len(rows)} shown",
                    total=int(total),
                ),
                row_count=len(rows),
                truncated=int(total) > len(rows),
            )

        if cmd.kind == "query_gid":
            gid = (cmd.arg or "").strip()
            if not gid:
                return LedgerQueryResult(
                    ok=False,
                    message=f"gid is required.\n{config.OPS_TEMPLATE}",
                )
            rows = list(
                conn.execute(
                    f"SELECT {gid_cols} FROM tasks "
                    "WHERE task_id=? OR filename=? OR url=? "
                    "ORDER BY updated_at DESC LIMIT 5",
                    (gid, gid, gid),
                ).fetchall()
            )
            if not rows:
                return LedgerQueryResult(
                    ok=True, message=f"not found: {gid}", row_count=0
                )
            return LedgerQueryResult(
                ok=True, message=_format_gid(rows), row_count=len(rows)
            )

        if cmd.kind == "query_export":
            rows = list(
                conn.execute(
                    f"SELECT {export_cols} FROM tasks "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (_EXPORT_HARD_CAP + 1,),
                ).fetchall()
            )
            truncated = len(rows) > _EXPORT_HARD_CAP
            if truncated:
                rows = rows[:_EXPORT_HARD_CAP]
            path = _write_export_xlsx(rows)
            msg = f"export {len(rows)} rows xlsx (UTC timestamps)"
            if truncated:
                msg += f" truncated=true cap={_EXPORT_HARD_CAP}"
            return LedgerQueryResult(
                ok=True,
                message=msg,
                file_path=path,
                row_count=len(rows),
                truncated=truncated,
            )

        return LedgerQueryResult(ok=False, message=config.OPS_TEMPLATE)
    finally:
        conn.close()
