import logging
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import ensure_dirs
from handlers.get_texts import ensure_worker, handle_get_texts
from inbox_watcher import scan_existing, start_watcher
import queue_manager
from router import register

_log = logging.getLogger("hermes_auto_extract")


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _register_routes():
    register("get-texts", handle_get_texts)


def main():
    _setup_logging()
    ensure_dirs()
    queue_manager.load()
    _register_routes()
    ensure_worker()
    scan_existing()
    observer = start_watcher()
    _log.info("service running")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        _log.info("shutting down")
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
