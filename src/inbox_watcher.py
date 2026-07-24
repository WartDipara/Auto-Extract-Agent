import json
import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config
from router import dispatch

_log = logging.getLogger(__name__)

_SETTLE_SEC = 0.4
_PROCESSING = set()


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
            return
        _log.info("inbox accepted: %s", path.name)
        dispatch(data, path)
    except json.JSONDecodeError as exc:
        _log.error("invalid json %s: %s", path.name, exc)
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


def scan_existing():
    for path in sorted(config.INBOX_DIR.glob("*.json")):
        _process_file(path)


def start_watcher() -> Observer:
    config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(_InboxHandler(), str(config.INBOX_DIR), recursive=False)
    observer.start()
    _log.info("watching inbox: %s", config.INBOX_DIR)
    return observer
