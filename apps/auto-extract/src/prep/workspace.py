from __future__ import annotations

import logging
from pathlib import Path

from shared.archive_contract import rmtree_force

_log = logging.getLogger(__name__)

__all__ = ["rmtree_force", "clear_signed_apks"]


def clear_signed_apks(task_root: Path):
    for pattern in ("*_signed.apk", "*.unsigned.apk", "*.aligned.apk", "*.idsig"):
        for tmp in Path(task_root).glob(pattern):
            try:
                tmp.unlink()
            except OSError as exc:
                _log.warning("cannot remove %s: %s", tmp, exc)
