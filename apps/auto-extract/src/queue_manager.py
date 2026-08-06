from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import config
import pipeline_queues as pq
import task_store
from downloader import filename_from_url
from models import TERMINAL_STATUSES, QueueState, Task
from shared.archive_contract import utc_now

_log = logging.getLogger(__name__)

_state = QueueState()
_lock = threading.Lock()
_memory: dict[str, Task] = {}


def buf_done_zip_for(result_csv: str) -> str:
    if not result_csv:
        return ""
    stem = Path(result_csv).stem
    return str((config.BUF_DONE_DIR / f"{stem}.zip").resolve())


def _task_to_dict(task: Task) -> dict:
    return {
        "task_id": task.task_id,
        "url": task.url,
        "source_file": task.source_file,
        "filename": task.filename,
        "label": task.label,
        "status": task.status,
        "error": task.error,
        "result_csv": task.result_csv,
        "session_id": task.session_id,
        "buf_done_zip": task.buf_done_zip or buf_done_zip_for(task.result_csv),
        "adb_serial": task.adb_serial,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "finished_at": task.finished_at,
        "im_delivered_at": task.im_delivered_at,
        "im_chat_id": task.im_chat_id,
        "im_sender_id": task.im_sender_id,
        "im_deliver_error": task.im_deliver_error,
        "run_gen": int(task.run_gen or 0),
    }


def _write_status_unlocked() -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    active = [
        _task_to_dict(t)
        for t in _memory.values()
        if t.status not in TERMINAL_STATUSES
    ]
    recent = [
        _task_to_dict(t)
        for t in task_store.list_recent_done(config.QUEUE_RECENT_DONE_MAX)
    ]
    payload = {
        "updated_at": utc_now(),
        "active": active,
        "recent_done": recent,
    }
    path = config.QUEUE_STATUS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load() -> None:
    task_store.open_store()
    with _lock:
        _memory.clear()
        _state.next_seq = task_store.get_next_seq()
        for task in task_store.list_active():
            _memory[task.task_id] = task
        _write_status_unlocked()
    _log.info(
        "queue_manager load active=%s next_seq=%s",
        len(_memory),
        _state.next_seq,
    )


def has_source_file(source_file: str) -> bool:
    return task_store.has_source_file(source_file)


def has_active_url(url: str) -> bool:
    return task_store.has_active_url((url or "").strip())


def urls_already_active(urls: list) -> bool:
    cleaned = [(u or "").strip() for u in urls if (u or "").strip()]
    if not cleaned:
        return False
    return all(task_store.has_active_url(u) for u in cleaned)


def _reset_for_overwrite(
    existing: Task,
    *,
    url: str,
    source_file: str,
    filename: str,
    im_chat_id: str,
    im_sender_id: str,
) -> Task:
    """Same task_id/filename row: bump run_gen and requeue from download."""
    new_gen = int(existing.run_gen or 0) + 1
    updated = task_store.update_task(
        existing.task_id,
        url=url,
        source_file=source_file,
        filename=filename,
        label="",
        labels={},
        status="queued",
        error="",
        result_csv="",
        session_id="",
        buf_done_zip="",
        adb_serial="",
        hotfix_has_files="",
        hotfix_pull_source="",
        screen_reached="",
        finished_at="",
        im_delivered_at="",
        im_deliver_error="",
        im_chat_id=im_chat_id,
        im_sender_id=im_sender_id,
        run_gen=new_gen,
    )
    if updated is None:
        raise RuntimeError(f"overwrite failed task_id={existing.task_id}")
    _memory[updated.task_id] = updated
    _log.info(
        "overwrite enqueued %s filename=%s gen=%s chat=%s sender=%s",
        updated.task_id,
        filename,
        new_gen,
        im_chat_id or "-",
        im_sender_id or "-",
    )
    return updated


def enqueue_urls(
    urls: list, source_file: str, *, im_chat_id: str = "", im_sender_id: str = ""
) -> list:
    created: list[Task] = []
    chat = (im_chat_id or "").strip()
    sender = (im_sender_id or "").strip()
    source = (source_file or "").strip()
    with _lock:
        if source and task_store.has_source_file(source):
            _log.info(
                "skip enqueue; source_file already in ledger: %s", source
            )
            return []
        for url in urls:
            url = (url or "").strip()
            if not url:
                continue
            filename = filename_from_url(url)
            existing = task_store.get_task_by_filename(filename)
            if existing is not None:
                # True overwrite: reset same row and re-run from download.
                if existing.status == "on_extract":
                    try:
                        from opencode_session import interrupt_active_run

                        interrupt_active_run()
                    except Exception:
                        _log.exception(
                            "interrupt on overwrite failed task_id=%s",
                            existing.task_id,
                        )
                task = _reset_for_overwrite(
                    existing,
                    url=url,
                    source_file=source_file,
                    filename=filename,
                    im_chat_id=chat,
                    im_sender_id=sender,
                )
                created.append(task)
                continue
            task_id = f"t-{_state.next_seq:04d}"
            _state.next_seq += 1
            task = Task(
                task_id=task_id,
                url=url,
                source_file=source_file,
                filename=filename,
                status="queued",
                im_chat_id=chat,
                im_sender_id=sender,
                run_gen=0,
            )
            task_store.insert_task(task)
            _memory[task.task_id] = task
            created.append(task)
            _log.info(
                "enqueued %s %s filename=%s chat=%s sender=%s",
                task_id,
                url,
                filename,
                chat or "-",
                sender or "-",
            )
        task_store.set_next_seq(_state.next_seq)
        _write_status_unlocked()
    for task in created:
        pq.put_download(task)
    return created


def update_task(
    task_id: str, *, expected_run_gen: int | None = None, **fields
) -> Task | None:
    updated = task_store.update_task(
        task_id, expected_run_gen=expected_run_gen, **fields
    )
    if updated is None:
        return None
    with _lock:
        if updated.status in TERMINAL_STATUSES:
            _memory.pop(task_id, None)
        else:
            _memory[task_id] = updated
        _write_status_unlocked()
    return updated


def get_task(task_id: str) -> Task | None:
    with _lock:
        mem = _memory.get(task_id)
        if mem is not None:
            return mem
    return task_store.get_task(task_id)


def list_tasks() -> list:
    with _lock:
        return list(_memory.values())


def append_session_record(task: Task):
    if not task.session_id:
        return
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "session_id": task.session_id,
        "task_id": task.task_id,
        "url": task.url,
        "filename": task.filename,
        "label": task.label,
        "status": task.status,
        "result_csv": task.result_csv,
        "source_file": task.source_file,
        "finished_at": utc_now(),
        "run_gen": int(task.run_gen or 0),
    }
    with config.SESSIONS_FILE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    _log.info("session recorded: %s -> %s", task.task_id, task.session_id)
