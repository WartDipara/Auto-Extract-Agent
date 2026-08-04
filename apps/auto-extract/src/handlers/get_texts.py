import logging
import shutil
import time
from pathlib import Path

import config
import queue_manager
from pipeline import start_pipeline

_log = logging.getLogger(__name__)


def _move_processed(source_path: Path):
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.PROCESSED_DIR / source_path.name
    if dest.exists():
        dest = config.PROCESSED_DIR / f"{source_path.stem}_{int(time.time())}{source_path.suffix}"
    shutil.move(str(source_path), str(dest))
    _log.info("moved inbox file to %s", dest)


def ensure_worker():
    start_pipeline()


def handle_get_texts(body: dict, source_path: Path):
    urls = body.get("urls") if isinstance(body, dict) else None
    if not isinstance(urls, list) or not urls:
        _log.warning("get-texts missing urls: %s", source_path.name)
        _move_processed(source_path)
        return
    im_chat_id = ""
    if isinstance(body, dict):
        im_chat_id = str(body.get("im_chat_id") or "").strip()
    ensure_worker()
    queue_manager.enqueue_urls(
        urls, source_file=source_path.name, im_chat_id=im_chat_id
    )
    _move_processed(source_path)
