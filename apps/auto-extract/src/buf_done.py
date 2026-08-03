"""Post-process result CSVs into an encrypted .bin under buf_done/ (background)."""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

import pyzipper

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


def _zip_password() -> bytes:
    password = (config.ZIP_PASSWORD or "").strip()
    if not password:
        raise RuntimeError("ZIP_PASSWORD missing in apps/auto-extract/.env")
    return password.encode("utf-8")


def pack_result_zip(primary_csv: Path, *, out_dir: Path | None = None) -> Path:
    """Encrypt primary (+ optional _T) into ``buf_done/{stem}.bin``. Keeps source CSVs."""
    primary = Path(primary_csv)
    if not primary.is_file():
        raise FileNotFoundError(primary)
    dest_dir = Path(out_dir) if out_dir is not None else config.BUF_DONE_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"{primary.stem}.bin"
    members = collect_result_csvs(primary)
    password = _zip_password()
    with pyzipper.AESZipFile(
        out_path,
        "w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES,
    ) as zf:
        zf.setpassword(password)
        for path in members:
            zf.write(path, arcname=path.name)
    _log.info(
        "buf_done bin: %s members=%s",
        out_path,
        [p.name for p in members],
    )
    print(
        f"buf_done bin: {out_path} ({len(members)} file{'s' if len(members) != 1 else ''})",
        flush=True,
    )
    return out_path


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
