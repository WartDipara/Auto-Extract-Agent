from __future__ import annotations

import argparse
import atexit
import logging
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parent
_APP = _SRC.parent
_REPO = _APP.parent.parent
for p in (_SRC, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import config  # noqa: E402
from audit import write_audit  # noqa: E402
from collector import collect_candidates  # noqa: E402
from lockfile import acquire_lock, release_lock  # noqa: E402
from recheck import recheck_candidates  # noqa: E402
from sweeper import sweep_all  # noqa: E402
from shared.service_log import setup_service_logging  # noqa: E402

_log = logging.getLogger("gc_module")


def run_once(*, dry_run: bool) -> dict:
    marked = collect_candidates()
    write_audit(
        "mark",
        dry_run=dry_run,
        count=len(marked),
        task_ids=[g.task_id for g in marked],
    )
    passed, dropped = recheck_candidates(marked)
    write_audit(
        "recheck",
        dry_run=dry_run,
        passed=len(passed),
        dropped=[{"task_id": t, "reason": r} for t, r in dropped],
    )
    results = sweep_all(passed, dry_run=dry_run)
    write_audit(
        "sweep",
        dry_run=dry_run,
        results=results,
        deleted=sum(1 for r in results if r.get("status") == "deleted"),
        skipped=sum(1 for r in results if r.get("status") == "skipped"),
        missing=sum(1 for r in results if r.get("status") == "missing"),
        dry_run_n=sum(1 for r in results if r.get("status") == "dry_run"),
    )
    return {
        "marked": len(marked),
        "passed": len(passed),
        "dropped": len(dropped),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="GC registered module artifacts after unified retention."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single mark-recheck-sweep cycle then exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List deletions without removing files.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Loop interval seconds (default 3600 from config).",
    )
    args = parser.parse_args(argv)

    setup_service_logging(config.SERVICE_LOG)

    dry_run = bool(args.dry_run or config.DRY_RUN_ENV)
    interval = (
        float(args.interval)
        if args.interval is not None
        else float(config.INTERVAL_SEC)
    )

    _log.info(
        "gc-module start dry_run=%s retention_days=%s interval=%s",
        dry_run,
        config.RETENTION_DAYS,
        interval,
    )
    _log.info("TASKS_DB=%s", config.TASKS_DB)
    for spec in config.MODULES:
        _log.info(
            "module=%s table=%s workspace=%s buf_done=%s",
            spec.module_id,
            spec.tasks_table,
            spec.workspace_root,
            spec.buf_done_dir,
        )
    _log.info("WORKSPACE_ROOT=%s", config.WORKSPACE_ROOT)
    _log.info("RESULT_DIR=%s", config.RESULT_DIR)
    _log.info("BUF_DONE_DIR=%s", config.BUF_DONE_DIR)
    _log.info("DOWNLOADS_DIR=%s", config.DOWNLOADS_DIR)

    if not acquire_lock():
        return 2
    atexit.register(release_lock)

    if args.once or interval <= 0:
        summary = run_once(dry_run=dry_run)
        _log.info(
            "gc once marked=%s passed=%s dropped=%s actions=%s",
            summary["marked"],
            summary["passed"],
            summary["dropped"],
            len(summary["results"]),
        )
        return 0

    while True:
        try:
            summary = run_once(dry_run=dry_run)
            _log.info(
                "gc tick marked=%s passed=%s dropped=%s actions=%s",
                summary["marked"],
                summary["passed"],
                summary["dropped"],
                len(summary["results"]),
            )
        except Exception:
            _log.exception("gc tick failed")
            write_audit("error", message="tick_failed")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
