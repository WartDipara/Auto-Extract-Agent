"""Read Module A queue_status.json snapshot."""

from __future__ import annotations

import json
from pathlib import Path


def read_queue_status(path: Path) -> dict:
    if not path.is_file():
        return {"active": [], "recent_done": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"active": [], "recent_done": []}
    if not isinstance(data, dict):
        return {"active": [], "recent_done": []}
    return {
        "active": list(data.get("active") or []),
        "recent_done": list(data.get("recent_done") or []),
        "updated_at": data.get("updated_at") or "",
    }


def find_by_source(status: dict, source_file: str) -> tuple[dict | None, dict | None]:
    """Return first (active_row, done_row) matching source_file name."""
    active_rows, done_rows = list_by_source(status, source_file)
    active = active_rows[0] if active_rows else None
    done = done_rows[0] if done_rows else None
    return active, done


def list_by_source(
    status: dict, source_file: str
) -> tuple[list[dict], list[dict]]:
    """Return all (active_rows, done_rows) matching source_file name."""
    name = Path(source_file).name
    active = [
        row
        for row in status.get("active") or []
        if Path(str(row.get("source_file") or "")).name == name
    ]
    done = [
        row
        for row in status.get("recent_done") or []
        if Path(str(row.get("source_file") or "")).name == name
    ]
    return active, done
