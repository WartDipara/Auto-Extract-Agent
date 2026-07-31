"""IM module entry: channel-routed courier → Module A inbox / buf_done."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import config
from channels.factory import create_channel
from courier import Courier


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    print(f"im-module channel={config.IM_CHANNEL}", flush=True)
    print(f"im-module inbox={config.INBOX_DIR}", flush=True)
    print(f"im-module queue_status={config.QUEUE_STATUS_FILE}", flush=True)
    print(f"im-module buf_done={config.BUF_DONE_DIR}", flush=True)
    Courier(create_channel(config.IM_CHANNEL)).start()


if __name__ == "__main__":
    main()
