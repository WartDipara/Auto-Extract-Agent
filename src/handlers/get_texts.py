import logging
import shutil
import threading
import time
from pathlib import Path

import config
import queue_manager
from apk_meta import extract_labels, primary_label
from downloader import download
from hermes_bridge import (
    append_session_to_log,
    archive_csv,
    classify_csv,
    clean_result_csv,
    cleanup_apk,
    ensure_csv_after_hermes,
    ensure_workspace_clean,
    invoke_hermes,
    place_apk,
    read_session_id_from_log,
    wait_for_csv,
)
from models import Task

_log = logging.getLogger(__name__)

_worker_lock = threading.Lock()
_worker_started = False


def _move_processed(source_path: Path):
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.PROCESSED_DIR / source_path.name
    if dest.exists():
        dest = config.PROCESSED_DIR / f"{source_path.stem}_{int(time.time())}{source_path.suffix}"
    shutil.move(str(source_path), str(dest))
    _log.info("moved inbox file to %s", dest)


def _recover_if_needed(task: Task) -> bool:
    if task.status == "downloading":
        queue_manager.update_task(task.task_id, status="queued")
        return True
    if task.status in ("submitting", "waiting_csv"):
        if task.filename:
            cleanup_apk(task.filename)
        queue_manager.update_task(
            task.task_id,
            status="failed",
            error="interrupted mid-hermes",
        )
        return True
    return False


def _ensure_apk(task: Task) -> Path:
    if task.status == "downloaded" and task.filename:
        local = config.DOWNLOADS_DIR / task.filename
        if local.is_file():
            if not task.labels:
                labels = extract_labels(local)
                queue_manager.update_task(
                    task.task_id,
                    labels=labels,
                    label=primary_label(labels),
                )
            return local
    queue_manager.update_task(task.task_id, status="downloading")
    apk_path = download(task.url)
    labels = extract_labels(apk_path)
    queue_manager.update_task(
        task.task_id,
        status="downloaded",
        filename=apk_path.name,
        labels=labels,
        label=primary_label(labels),
    )
    return apk_path


def _other_hermes_busy(task_id: str) -> str | None:
    for item in queue_manager.list_tasks():
        if item.task_id == task_id:
            continue
        if item.status in ("submitting", "waiting_csv"):
            return item.task_id
    return None


def _process_task(task: Task):
    task_id = task.task_id
    ensure_workspace_clean()
    apk_path = _ensure_apk(task)
    filename = apk_path.name
    label = task.label or ""

    busy = _other_hermes_busy(task_id)
    if busy is not None:
        _log.error("hermes busy (%s), refuse submit for %s", busy, task_id)
        queue_manager.update_task(
            task_id,
            status="failed",
            error=f"hermes busy: {busy}",
        )
        return

    queue_manager.update_task(task_id, status="submitting", filename=filename)
    place_apk(apk_path)
    result = invoke_hermes(filename)
    if result.returncode != 0:
        _log.error(
            "hermes nonzero exit %s: %s",
            result.returncode,
            (result.stderr or result.stdout or "").strip(),
        )

    queue_manager.update_task(task_id, status="waiting_csv")
    ensure_csv_after_hermes(filename, result.returncode)
    csv_path, text = wait_for_csv(filename, timeout_sec=config.CSV_GRACE_SEC)
    status = classify_csv(text)
    body_text, session_id = clean_result_csv(text)
    if not session_id:
        session_id = read_session_id_from_log(filename)
    archived = archive_csv(csv_path, Path(filename).stem, label, body_text)
    append_session_to_log(filename, session_id)
    cleanup_apk(filename)
    updated = queue_manager.update_task(
        task_id,
        status=status,
        result_csv=str(archived),
        session_id=session_id,
        error="" if status == "success" else body_text.strip().splitlines()[0],
    )
    if updated is not None:
        queue_manager.append_session_record(updated)
    _log.info(
        "task %s done status=%s label=%s session=%s",
        task_id,
        status,
        label or "-",
        session_id or "-",
    )


def _worker_loop():
    while True:
        task = queue_manager.get_next_runnable()
        if task is None:
            time.sleep(1.0)
            continue
        if _recover_if_needed(task):
            continue
        try:
            _process_task(task)
        except TimeoutError as exc:
            _log.error("%s", exc)
            if task.filename:
                cleanup_apk(task.filename)
            queue_manager.update_task(
                task.task_id,
                status="timeout",
                error=str(exc),
            )
        except Exception as exc:
            _log.exception("task %s failed: %s", task.task_id, exc)
            if task.filename:
                cleanup_apk(task.filename)
            queue_manager.update_task(
                task.task_id,
                status="failed",
                error=str(exc),
            )


def ensure_worker():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        thread = threading.Thread(
            target=_worker_loop,
            name="get-texts-worker",
            daemon=True,
        )
        thread.start()
        _worker_started = True
        _log.info("get-texts worker started")


def handle_get_texts(body: dict, source_path: Path):
    urls = body.get("urls") if isinstance(body, dict) else None
    if not isinstance(urls, list) or not urls:
        _log.warning("get-texts missing urls: %s", source_path.name)
        return
    ensure_worker()
    queue_manager.enqueue_urls(urls, source_file=source_path.name)
    _move_processed(source_path)
