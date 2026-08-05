from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

_log = logging.getLogger(__name__)


def ensure_state_dir() -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)


def write_audit(event: str, **fields: Any) -> None:
    ensure_state_dir()
    payload = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event,
        **fields,
    }
    line = json.dumps(payload, ensure_ascii=False)
    path = Path(config.AUDIT_PATH)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(line + "\n")
    _log.info("audit %s %s", event, {k: v for k, v in fields.items() if k != "paths"})
