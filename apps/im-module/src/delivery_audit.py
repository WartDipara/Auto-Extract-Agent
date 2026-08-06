from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)
_lock = threading.Lock()


def append_delivery_event(path: Path, event: dict[str, Any]) -> None:
    """Append one JSON line; never raise to callers."""
    target = Path(path)
    payload = dict(event)
    payload.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    try:
        with _lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fp:
                fp.write(line)
    except OSError:
        _log.exception("delivery audit write failed path=%s", target)
