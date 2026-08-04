from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def write_inbox_json(inbox_dir: Path, payload: dict[str, Any], *, request_id: str) -> Path:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    name = f"im_{request_id}.json"
    dest = inbox_dir / name
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(dest)
    return dest


def new_request_id() -> str:
    return f"{int(time.time())}_{time.time_ns() % 1_000_000:06d}"
