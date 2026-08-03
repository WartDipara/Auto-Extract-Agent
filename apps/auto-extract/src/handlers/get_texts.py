import logging
import shutil
import threading
import time
from pathlib import Path

import config
import queue_manager
from apk_meta import extract_labels, primary_label
from buf_done import enqueue_buf_done, ensure_buf_done_worker
from downloader import download
from errors import ErrorInfo, emit, normalize, stage_scope
from extract_bridge import (
    append_session_to_log,
    archive_csv,
    classify_csv,
    cleanup_download_apk,
    ensure_csv_after_agent,
    invoke_extract_agent,
    read_session_id_from_log,
    wait_for_csv,
)
from models import Task
from prep import run_device_prep
from shared.archive_contract import (
    clean_result_csv,
    mark_module_a_done,
    reset_task_workspace,
    task_layout,
    utc_now,
    write_meta,
)

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
    if task.status in ("submitting", "archiving", "preparing"):
        if task.filename:
            cleanup_download_apk(task.filename)
        emit(
            ErrorInfo(
                code="PIPELINE_INTERRUPTED",
                message="interrupted mid-pipeline",
                stage=task.status,
                status="failed",
            ),
            task=task,
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


def _process_task(task: Task) -> Path | None:
    """Run pipeline. Returns task_root when available (for error sinks)."""
    task_id = task.task_id
    filename = ""
    task_root: Path | None = None
    try:
        with stage_scope("download"):
            apk_path = _ensure_apk(task)
        filename = apk_path.name
        task_key = Path(filename).stem
        label = task.label or ""

        print(f"task workspace: {task_key}", flush=True)
        with stage_scope("prepare"):
            task_root = reset_task_workspace(config.WORKSPACE_ROOT, task_key)
            queue_manager.update_task(task_id, status="preparing", filename=filename)
            prep = run_device_prep(apk_path=apk_path, task_root=task_root)
        _log.info(
            "prep finished package=%s pull=%s hotfix=%s screen=%s",
            prep.package_name,
            prep.pull_source,
            prep.hotfix_has_files,
            prep.screen_reached,
        )

        with stage_scope("extract"):
            queue_manager.update_task(task_id, status="submitting", filename=filename)
            result = invoke_extract_agent(
                filename,
                task_root=task_root,
                labels=task.labels,
                label=label,
            )
            if result.returncode != 0:
                _log.error(
                    "opencode nonzero exit %s: %s",
                    result.returncode,
                    (result.stderr or result.stdout or "").strip(),
                )

        with stage_scope("archive"):
            queue_manager.update_task(task_id, status="archiving")
            ensure_csv_after_agent(filename, result.returncode)
            csv_path, text = wait_for_csv(filename, timeout_sec=config.CSV_GRACE_SEC)
            status = classify_csv(text)
            body_text, session_id = clean_result_csv(text)
            if not session_id:
                session_id = read_session_id_from_log(filename)
            if not session_id:
                from opencode_session import OpenCodeSessionManager

                session_id = OpenCodeSessionManager().lookup_session_id(task_key)
            archived = archive_csv(csv_path, task_key, label, body_text)
            enqueue_buf_done(archived)
            append_session_to_log(filename, session_id)
            err_line = ""
            error_info = None
            if status != "success":
                msg = (
                    body_text.strip().splitlines()[0]
                    if body_text.strip()
                    else status
                )
                error_info = ErrorInfo(
                    code=status.upper(),
                    message=msg,
                    stage="archive",
                    status=status,
                )
                err_line = error_info.to_line()
            updated = queue_manager.update_task(
                task_id,
                status=status,
                result_csv=str(archived),
                session_id=session_id,
                error=err_line,
            )
            if updated is not None:
                queue_manager.append_session_record(updated)

            layout = task_layout(task_root)
            export_path = layout["opencode_export"]
            meta = {
                "task_id": task_id,
                "task_key": task_key,
                "session_id": session_id or "",
                "url": task.url,
                "filename": filename,
                "label": label,
                "status": status,
                "error": err_line,
                "result_csv": str(archived),
                "opencode_export": str(export_path) if export_path.is_file() else "",
                "finished_at": utc_now(),
            }
            if error_info is not None:
                meta["error_info"] = error_info.to_dict()
            write_meta(task_root, meta)
            if status == "success":
                mark_module_a_done(task_root)
                print(f"module A done marker written: {task_key}", flush=True)

        print(
            f"module A task finished: {task_key} status={status} "
            f"label={label or '-'} session={session_id or '-'}",
            flush=True,
        )
        _log.info(
            "task %s done status=%s label=%s session=%s",
            task_id,
            status,
            label or "-",
            session_id or "-",
        )
        return task_root
    finally:
        cleanup_download_apk(filename)


def _task_root_for(task: Task) -> Path | None:
    if not task.filename:
        return None
    root = config.WORKSPACE_ROOT / Path(task.filename).stem
    return root if root.is_dir() else None


def _worker_loop():
    while True:
        task = queue_manager.get_next_runnable()
        if task is None:
            time.sleep(1.0)
            continue
        if _recover_if_needed(task):
            continue
        task_root: Path | None = None
        try:
            task_root = _process_task(task)
        except Exception as exc:
            info = normalize(exc)
            emit(
                info,
                task=task,
                task_root=task_root or _task_root_for(task),
            )


def ensure_worker():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        ensure_buf_done_worker()
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
        _move_processed(source_path)
        return
    ensure_worker()
    queue_manager.enqueue_urls(urls, source_file=source_path.name)
    _move_processed(source_path)
