import json
import logging
import shutil
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config
from router import dispatch

_log = logging.getLogger(__name__)

_SETTLE_SEC = 0.4
_RESCAN_SEC = 3.0
_PROCESSING = set()


def _move_aside(path: Path, *, prefix: str = "") -> None:
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{prefix}{path.name}" if prefix else path.name
    dest = config.PROCESSED_DIR / name
    if dest.exists():
        dest = config.PROCESSED_DIR / f"{Path(name).stem}_{int(time.time())}{path.suffix}"
    shutil.move(str(path), str(dest))
    _log.info("moved inbox file to %s", dest)


def _read_json(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        _log.warning("inbox json root must be object: %s", path.name)
        return None
    return data


def _process_file(path: Path):
    key = str(path.resolve())
    if key in _PROCESSING:
        return
    if not path.is_file() or path.suffix.lower() != ".json":
        return
    time.sleep(_SETTLE_SEC)
    if not path.is_file():
        return
    _PROCESSING.add(key)
    try:
        data = _read_json(path)
        if data is None:
            _move_aside(path, prefix="rejected_")
            return
        ok = dispatch(data, path)
        if not path.is_file():
            return
        if ok:
            _log.info("inbox accepted: %s", path.name)
            _move_aside(path)
        else:
            _log.warning("inbox rejected (not enqueued): %s", path.name)
            _move_aside(path, prefix="rejected_")
    except json.JSONDecodeError as exc:
        _log.error("invalid json %s: %s", path.name, exc)
        if path.is_file():
            _move_aside(path, prefix="rejected_")
    except Exception:
        # Leave file in inbox for rescan; do not swallow into processed.
        _log.exception("inbox process failed (kept for retry): %s", path.name)
    finally:
        _PROCESSING.discard(key)


class _InboxHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        _process_file(Path(event.src_path))

    def on_modified(self, event):
        if event.is_directory:
            return
        _process_file(Path(event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return
        # im-module writes atomically: tmp file renamed to *.json — a rename
        # only surfaces here on Windows (no on_created for the final name).
        _process_file(Path(event.dest_path))


def scan_existing():
    for path in sorted(config.INBOX_DIR.glob("*.json")):
        _process_file(path)


def _rescan_loop():
    while True:
        time.sleep(_RESCAN_SEC)
        try:
            scan_existing()
        except Exception:
            _log.exception("inbox rescan failed")


def start_watcher() -> Observer:
    config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(_InboxHandler(), str(config.INBOX_DIR), recursive=False)
    observer.start()
    threading.Thread(target=_rescan_loop, name="inbox-rescan", daemon=True).start()
    _log.info("watching inbox: %s", config.INBOX_DIR)
    return observer
