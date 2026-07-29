import datetime
import json
import logging
import threading

import config
from models import QueueState, Task

_log = logging.getLogger(__name__)

_TERMINAL = frozenset(
    {
        "success",
        "decrypt_failed",
        "assets_missing",
        "abnormal_exit",
        "failed",
        "timeout",
    }
)

_state = QueueState()
_lock = threading.Lock()


def load():
    """No disk queue; start empty each process."""
    with _lock:
        _state.next_seq = 1
        _state.tasks = []


def enqueue_urls(urls: list, source_file: str) -> list:
    with _lock:
        created = []
        for url in urls:
            url = (url or "").strip()
            if not url:
                continue
            task_id = f"t-{_state.next_seq:04d}"
            _state.next_seq += 1
            task = Task(task_id=task_id, url=url, source_file=source_file)
            _state.tasks.append(task)
            created.append(task)
            _log.info("enqueued %s %s", task_id, url)
        return created


def get_next_runnable() -> Task | None:
    with _lock:
        for task in _state.tasks:
            if task.status in ("downloading", "preparing", "submitting", "waiting_csv"):
                return task
        for task in _state.tasks:
            if task.status in ("queued", "downloaded"):
                return task
        return None


def update_task(task_id: str, **fields) -> Task | None:
    with _lock:
        for idx, task in enumerate(_state.tasks):
            if task.task_id != task_id:
                continue
            for key, value in fields.items():
                setattr(task, key, value)
            if task.status in _TERMINAL:
                _state.tasks.pop(idx)
            return task
        return None


def list_tasks() -> list:
    with _lock:
        return list(_state.tasks)


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
        "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    with config.SESSIONS_FILE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    _log.info("session recorded: %s -> %s", task.task_id, task.session_id)
