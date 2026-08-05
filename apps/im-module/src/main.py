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
    print(f"im-module tasks_db={config.TASKS_DB}", flush=True)
    Courier(create_channel(config)).start()


if __name__ == "__main__":
    main()
