import datetime
import json
import logging

import config
from models import QueueState, Task

_log = logging.getLogger(__name__)

_state = QueueState()


def _task_to_dict(task: Task) -> dict:
    return {
        "task_id": task.task_id,
        "url": task.url,
        "source_file": task.source_file,
        "filename": task.filename,
        "status": task.status,
        "error": task.error,
        "result_csv": task.result_csv,
        "session_id": task.session_id,
    }


def _task_from_dict(data: dict) -> Task:
    return Task(
        task_id=data["task_id"],
        url=data["url"],
        source_file=data.get("source_file", ""),
        filename=data.get("filename", ""),
        status=data.get("status", "queued"),
        error=data.get("error", ""),
        result_csv=data.get("result_csv", ""),
        session_id=data.get("session_id", ""),
    )


def _save():
    payload = {
        "next_seq": _state.next_seq,
        "tasks": [_task_to_dict(t) for t in _state.tasks],
    }
    config.QUEUE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load():
    if not config.QUEUE_FILE.is_file():
        _state.next_seq = 1
        _state.tasks = []
        return
    raw = json.loads(config.QUEUE_FILE.read_text(encoding="utf-8"))
    _state.next_seq = int(raw.get("next_seq", 1))
    _state.tasks = [_task_from_dict(item) for item in raw.get("tasks", [])]


def enqueue_urls(urls: list, source_file: str) -> list:
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
    _save()
    return created


def get_next_runnable() -> Task | None:
    for task in _state.tasks:
        if task.status in ("downloading", "submitting", "waiting_csv"):
            return task
    for task in _state.tasks:
        if task.status in ("queued", "downloaded"):
            return task
    return None


def update_task(task_id: str, **fields) -> Task | None:
    for task in _state.tasks:
        if task.task_id != task_id:
            continue
        for key, value in fields.items():
            setattr(task, key, value)
        _save()
        return task
    return None


def list_tasks() -> list:
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
        "status": task.status,
        "result_csv": task.result_csv,
        "source_file": task.source_file,
        "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    with config.SESSIONS_FILE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    _log.info("session recorded: %s -> %s", task.task_id, task.session_id)
