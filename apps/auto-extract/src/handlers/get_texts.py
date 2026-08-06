import logging
from pathlib import Path

import queue_manager
from pipeline import start_pipeline

_log = logging.getLogger(__name__)


def ensure_worker():
    start_pipeline()


def handle_get_texts(body: dict, source_path: Path) -> bool:
    """Accept get-texts payload. Return True if ledger accepted or already covered."""
    urls = body.get("urls") if isinstance(body, dict) else None
    if not isinstance(urls, list) or not urls:
        _log.warning("get-texts missing urls: %s", source_path.name)
        return False
    cleaned = [str(u).strip() for u in urls if str(u).strip()]
    if not cleaned:
        _log.warning("get-texts empty urls after trim: %s", source_path.name)
        return False
    im_chat_id = ""
    im_sender_id = ""
    if isinstance(body, dict):
        im_chat_id = str(body.get("im_chat_id") or "").strip()
        im_sender_id = str(body.get("im_sender_id") or "").strip()
    ensure_worker()
    created = queue_manager.enqueue_urls(
        cleaned,
        source_file=source_path.name,
        im_chat_id=im_chat_id,
        im_sender_id=im_sender_id,
    )
    if created:
        return True
    # Same inbox file replayed, or same URL already running under another source.
    if queue_manager.has_source_file(source_path.name):
        return True
    if queue_manager.urls_already_active(cleaned):
        _log.info(
            "inbox noop; urls already active source=%s", source_path.name
        )
        return True
    return False
