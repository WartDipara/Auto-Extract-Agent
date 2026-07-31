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
    """Return (active_row, done_row) matching source_file name."""
    name = Path(source_file).name
    active = None
    for row in status.get("active") or []:
        if Path(str(row.get("source_file") or "")).name == name:
            active = row
            break
    done = None
    for row in status.get("recent_done") or []:
        if Path(str(row.get("source_file") or "")).name == name:
            done = row
            break
    return active, done
