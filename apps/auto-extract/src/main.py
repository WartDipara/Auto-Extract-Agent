import logging
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parent
_APP = _SRC.parent
_REPO = _SRC.parent.parent.parent  # Auto-Extract-Agent
for _p in (_APP, _SRC, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config
from config import assert_extract_agent_ready, ensure_dirs
from buf_done import ensure_buf_done_worker
from handlers.get_texts import ensure_worker, handle_get_texts
from inbox_watcher import scan_existing, start_watcher
import queue_manager
from router import register

_log = logging.getLogger("auto_extract")


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _log_agent_paths():
    _log.info("agent=opencode | workspace=%s", config.WORKSPACE_ROOT.resolve())


def _register_routes():
    register("get-texts", handle_get_texts)


def main():
    _setup_logging()
    assert_extract_agent_ready()
    ensure_dirs()
    _log_agent_paths()
    queue_manager.load()
    _register_routes()
    ensure_buf_done_worker()
    ensure_worker()
    scan_existing()
    observer = start_watcher()
    _log.info("auto-extract service running")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        _log.info("shutting down")
        try:
            from opencode_session import interrupt_active_run

            interrupt_active_run()
        except Exception as exc:
            _log.warning("interrupt_active_run failed: %s", exc)
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
