"""Post-process result CSVs into a single zip under buf_done/ (background)."""

from __future__ import annotations

import logging
import queue
import threading
import zipfile
from pathlib import Path

import config

_log = logging.getLogger(__name__)

_job_queue: queue.Queue[Path | None] = queue.Queue()
_worker_lock = threading.Lock()
_worker_started = False


def collect_result_csvs(primary_csv: Path) -> list[Path]:
    """Primary result CSV plus optional ``{stem}_T.csv`` sibling."""
    primary = Path(primary_csv)
    files = [primary]
    trad = primary.with_name(f"{primary.stem}_T{primary.suffix}")
    if trad.is_file():
        files.append(trad)
    return files


def pack_result_zip(primary_csv: Path, *, out_dir: Path | None = None) -> Path:
    """Zip primary (+ optional _T) into ``buf_done/{stem}.zip``. Keeps source CSVs."""
    primary = Path(primary_csv)
    if not primary.is_file():
        raise FileNotFoundError(primary)
    dest_dir = Path(out_dir) if out_dir is not None else config.BUF_DONE_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / f"{primary.stem}.zip"
    members = collect_result_csvs(primary)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in members:
            zf.write(path, arcname=path.name)
    _log.info(
        "buf_done zip: %s members=%s",
        zip_path,
        [p.name for p in members],
    )
    print(
        f"buf_done zip: {zip_path} ({len(members)} file{'s' if len(members) != 1 else ''})",
        flush=True,
    )
    return zip_path


def _worker_loop():
    while True:
        primary = _job_queue.get()
        try:
            if primary is None:
                return
            pack_result_zip(primary)
        except Exception as exc:
            _log.exception("buf_done pack failed for %s: %s", primary, exc)
            print(f"buf_done pack failed: {primary} ({exc})", flush=True)
        finally:
            _job_queue.task_done()


def ensure_buf_done_worker():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        config.BUF_DONE_DIR.mkdir(parents=True, exist_ok=True)
        thread = threading.Thread(
            target=_worker_loop,
            name="buf-done-worker",
            daemon=True,
        )
        thread.start()
        _worker_started = True
        _log.info("buf-done worker started")


def enqueue_buf_done(primary_csv: Path) -> None:
    """Queue zip packing; returns immediately. Failures stay in the worker."""
    ensure_buf_done_worker()
    _job_queue.put(Path(primary_csv))
