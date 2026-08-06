from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import config
import pipeline_queues as pq
import task_store
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
    return str((config.BUF_DONE_DIR / f"{stem}.bin").resolve())


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
    }


def _write_status_unlocked() -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    active = [
        _task_to_dict(t)
        for t in _memory.values()
        if t.status not in TERMINAL_STATUSES
    ]
    recent = [_task_to_dict(t) for t in task_store.list_recent_done(config.QUEUE_RECENT_DONE_MAX)]
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


def enqueue_urls(
    urls: list, source_file: str, *, im_chat_id: str = "", im_sender_id: str = ""
) -> list:
    created: list[Task] = []
    chat = (im_chat_id or "").strip()
    sender = (im_sender_id or "").strip()
    with _lock:
        for url in urls:
            url = (url or "").strip()
            if not url:
                continue
            task_id = f"t-{_state.next_seq:04d}"
            _state.next_seq += 1
            task = Task(
                task_id=task_id,
                url=url,
                source_file=source_file,
                status="queued",
                im_chat_id=chat,
                im_sender_id=sender,
            )
            task_store.insert_task(task)
            _memory[task.task_id] = task
            created.append(task)
            _log.info(
                "enqueued %s %s chat=%s sender=%s",
                task_id,
                url,
                chat or "-",
                sender or "-",
            )
        task_store.set_next_seq(_state.next_seq)
        _write_status_unlocked()
    for task in created:
        pq.put_download(task)
    return created


def update_task(task_id: str, **fields) -> Task | None:
    updated = task_store.update_task(task_id, **fields)
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
    }
    with config.SESSIONS_FILE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    _log.info("session recorded: %s -> %s", task.task_id, task.session_id)
