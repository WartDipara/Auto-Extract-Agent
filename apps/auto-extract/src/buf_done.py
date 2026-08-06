from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path

import pyzipper

import config
import queue_manager

_log = logging.getLogger(__name__)

_worker_lock = threading.Lock()
_worker_started = False


@dataclass(frozen=True)
class BufDoneJob:
    primary_csv: Path
    task_id: str = ""


_job_queue: queue.Queue[BufDoneJob | None] = queue.Queue()


def collect_result_csvs(primary_csv: Path) -> list[Path]:
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
    primary = Path(primary_csv)
    if not primary.is_file():
        raise FileNotFoundError(primary)
    dest_dir = Path(out_dir) if out_dir is not None else config.BUF_DONE_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"{primary.stem}.zip"
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
        "buf_done zip: %s members=%s",
        out_path,
        [p.name for p in members],
    )
    return out_path


def _mark_pack_failed(task_id: str, primary: Path, exc: BaseException) -> None:
    if not task_id:
        return
    err = f"[BUF_DONE_PACK@archive] {primary.name}: {exc}"
    try:
        task = queue_manager.get_task(task_id)
        if task is None:
            _log.error("task_id=%s missing for buf_done error: %s", task_id, err)
            return
        if task.status != "success":
            _log.error(
                "task_id=%s buf_done pack failed while status=%s: %s",
                task_id,
                task.status,
                err,
            )
            return
        queue_manager.update_task(
            task_id,
            status="failed",
            error=err,
            expected_run_gen=int(task.run_gen or 0),
        )
        _log.error("task_id=%s %s", task_id, err)
    except Exception:
        _log.exception("task_id=%s failed to record buf_done error", task_id)


def _worker_loop() -> None:
    while True:
        job = _job_queue.get()
        try:
            if job is None:
                return
            pack_result_zip(job.primary_csv)
        except Exception as exc:
            primary = job.primary_csv if job is not None else Path("?")
            task_id = job.task_id if job is not None else ""
            _log.exception(
                "buf_done pack failed task_id=%s csv=%s: %s",
                task_id or "-",
                primary,
                exc,
            )
            _mark_pack_failed(task_id, primary, exc)
        finally:
            _job_queue.task_done()


def ensure_buf_done_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        config.BUF_DONE_DIR.mkdir(parents=True, exist_ok=True)
        threading.Thread(
            target=_worker_loop,
            name="buf-done-worker",
            daemon=True,
        ).start()
        _worker_started = True
        _log.info("buf-done worker started")


def enqueue_buf_done(primary_csv: Path, *, task_id: str = "") -> None:
    ensure_buf_done_worker()
    _job_queue.put(BufDoneJob(primary_csv=Path(primary_csv), task_id=task_id or ""))
