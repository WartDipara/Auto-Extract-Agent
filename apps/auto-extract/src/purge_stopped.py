"""
Purge task workspaces marked with .stop under apps/auto-extract/workspace.

Usage (from repo root):
  python apps/auto-extract/src/purge_stopped.py
  python apps/auto-extract/src/purge_stopped.py --interval 600
  .\\launch_purge_stopped.ps1
  .\\launch_purge_stopped.ps1 -IntervalSec 600
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parent
_REPO = _SRC.parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import config  # noqa: E402
from shared.archive_contract import purge_stopped_workspaces  # noqa: E402

_log = logging.getLogger("purge_stopped")


def _run_once() -> list[str]:
    root = config.WORKSPACE_ROOT
    deleted = purge_stopped_workspaces(root)
    if deleted:
        print(f"purged {len(deleted)} workspace(s): {', '.join(deleted)}", flush=True)
    else:
        print(f"no stopped workspaces under {root}", flush=True)
    return deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Delete workspace/<task_key> dirs that contain a .stop marker."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0,
        help="If >0, loop forever sleeping this many seconds between scans.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.interval and args.interval > 0:
        _log.info("purge loop interval=%ss workspace=%s", args.interval, config.WORKSPACE_ROOT)
        while True:
            _run_once()
            time.sleep(args.interval)
    _run_once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
