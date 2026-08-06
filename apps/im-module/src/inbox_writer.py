from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


def write_inbox_json(inbox_dir: Path, payload: dict[str, Any], *, request_id: str) -> Path:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    name = f"im_{request_id}.json"
    dest = (Path(inbox_dir) / name).resolve()
    tmp = dest.with_suffix(".tmp")
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(dest)
    if not dest.is_file() or dest.stat().st_size < 2:
        raise RuntimeError(f"inbox write verify failed: {dest}")
    return dest


def new_request_id() -> str:
    # Full uuid segment — avoid collisions from time_ns % 1_000_000 wrap.
    return f"{int(time.time())}_{uuid.uuid4().hex}"
