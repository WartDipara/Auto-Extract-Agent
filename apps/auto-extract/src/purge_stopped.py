from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
_REPO = _SRC.parent.parent.parent
_GC_MAIN = _REPO / "apps" / "gc-module" / "src" / "main.py"

_log = logging.getLogger("purge_stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "DEPRECATED wrapper → gc-module. "
            "Prefer launch_gc_module.ps1 / apps/gc-module."
        )
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0,
        help="If >0, forward as gc-module --interval (loop).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Forward --dry-run to gc-module.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _log.warning(
        "purge_stopped.py is deprecated; forwarding to gc-module "
        "(unified retention, not immediate .stop delete)"
    )

    if not _GC_MAIN.is_file():
        _log.error("gc-module main missing: %s", _GC_MAIN)
        return 1

    cmd = [sys.executable, str(_GC_MAIN)]
    if args.interval and args.interval > 0:
        cmd.extend(["--interval", str(args.interval)])
    else:
        cmd.append("--once")
    if args.dry_run:
        cmd.append("--dry-run")

    gc_src = _GC_MAIN.parent
    env_pythonpath = str(gc_src) + ";" + str(_REPO)
    import os

    env = os.environ.copy()
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        env_pythonpath if not prev else f"{env_pythonpath};{prev}"
    )
    env["PYTHONUTF8"] = "1"
    return int(subprocess.call(cmd, cwd=str(_REPO / "apps" / "gc-module"), env=env))


if __name__ == "__main__":
    raise SystemExit(main())
