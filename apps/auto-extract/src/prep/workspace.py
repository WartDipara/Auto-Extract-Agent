from __future__ import annotations

import logging
import shutil
import stat
import subprocess
import time
from pathlib import Path

_log = logging.getLogger(__name__)


def _on_rm_error(func, path, exc_info):
    try:
        Path(path).chmod(stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def rmtree_force(path: Path):
    if not path.exists():
        return
    for _ in range(5):
        try:
            shutil.rmtree(path, onerror=_on_rm_error)
        except OSError:
            pass
        if not path.exists():
            return
        subprocess.run(
            ["cmd", "/c", "rmdir", "/s", "/q", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if not path.exists():
            return
        time.sleep(0.4)
    if path.exists():
        _log.warning("rmtree_force incomplete: %s", path)


def clear_signed_apks(task_root: Path):
    for pattern in ("*_signed.apk", "*.unsigned.apk", "*.aligned.apk", "*.idsig"):
        for tmp in Path(task_root).glob(pattern):
            try:
                tmp.unlink()
            except OSError as exc:
                _log.warning("cannot remove %s: %s", tmp, exc)
