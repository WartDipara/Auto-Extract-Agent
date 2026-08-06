from __future__ import annotations

import logging
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
_APP = _SRC.parent
_REPO = _APP.parent.parent
for _p in (_SRC, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config
from channels.factory import create_channel
from courier import Courier
from shared.service_log import setup_service_logging


def main() -> None:
    setup_service_logging(config.SERVICE_LOG)
    _log = logging.getLogger("im_module")
    config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    _log.info("im-module channel=%s", config.IM_CHANNEL)
    _log.info("im-module inbox=%s", config.INBOX_DIR)
    _log.info("im-module tasks_db=%s", config.TASKS_DB)
    _log.info(
        "im-module modules=%s",
        [f"{m.module_id}:{m.tasks_table}" for m in config.MODULES],
    )
    Courier(create_channel(config)).start()


if __name__ == "__main__":
    main()
