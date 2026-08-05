from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import config
import pipeline_queues as pq
import queue_manager
import task_store
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
from opencode_session import OpenCodeSessionManager
from prep import run_device_stage, run_patch_stage
from prep.debuggable_apk import package_name_from_apk
from resource_pools import AdbPool, OpenCodePool
from shared.archive_contract import (
    clean_result_csv,
    reset_task_workspace,
    task_layout,
    utc_now,
    write_meta,
)

_log = logging.getLogger(__name__)

_started = False
_start_lock = threading.Lock()
_adb_pool: AdbPool | None = None
_opencode_pool: OpenCodePool | None = None
_HEARTBEAT_SEC = 5.0


def _write_heartbeat() -> None:
    path = config.HEARTBEAT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(utc_now() + "\n", encoding="utf-8")


def _heartbeat_loop() -> None:
    while True:
        try:
            _write_heartbeat()
        except Exception:
            _log.exception("heartbeat write failed")
        time.sleep(_HEARTBEAT_SEC)


def _pools() -> tuple[AdbPool, OpenCodePool]:
    global _adb_pool, _opencode_pool
    if _adb_pool is None:
        _adb_pool = AdbPool(wait_timeout_sec=config.DEVICE_WAIT_TIMEOUT_SEC)
    if _opencode_pool is None:
        _opencode_pool = OpenCodePool(
            config.OPENCODE_SLOTS,
            wait_timeout_sec=config.OPENCODE_WAIT_TIMEOUT_SEC,
        )
    return _adb_pool, _opencode_pool


def _fail(task: Task, code: str, message: str, stage: str) -> None:
    emit(
        ErrorInfo(
            code=code,
            message=message,
            stage=stage,
            status="failed",
        ),
        task=task,
        task_root=_task_root_for(task),
    )


def _task_root_for(task: Task) -> Path | None:
    if not task.filename:
        return None
    root = config.WORKSPACE_ROOT / Path(task.filename).stem
    return root if root.is_dir() else None


def _apk_path(task: Task) -> Path | None:
    if not task.filename:
        return None
    path = config.DOWNLOADS_DIR / task.filename
    return path if path.is_file() else None


def _signed_path(task: Task) -> Path | None:
    if not task.filename:
        return None
    stem = Path(task.filename).stem
    path = config.WORKSPACE_ROOT / stem / f"{stem}_signed.apk"
    return path if path.is_file() else None


def _download_loop() -> None:
    while True:
        task = pq.Q_DOWNLOAD.get()
        try:
            with stage_scope("download"):
                apk_path = download(task.url)
                labels = extract_labels(apk_path)
                updated = queue_manager.update_task(
                    task.task_id,
                    status="downloaded",
                    filename=apk_path.name,
                    labels=labels,
                    label=primary_label(labels),
                )
                if updated:
                    pq.put_patch(updated)
        except Exception as exc:
            emit(normalize(exc), task=task, task_root=None)
        finally:
            pq.Q_DOWNLOAD.task_done()


def _patch_loop() -> None:
    while True:
        task = pq.Q_PATCH.get()
        try:
            apk = _apk_path(task)
            if apk is None:
                queue_manager.update_task(task.task_id, status="queued", filename="")
                fresh = queue_manager.get_task(task.task_id)
                if fresh:
                    pq.put_download(fresh)
                continue
            with stage_scope("patch"):
                task_key = apk.stem
                task_root = reset_task_workspace(config.WORKSPACE_ROOT, task_key)
                run_patch_stage(task_root=task_root, apk_path=apk)
                updated = queue_manager.update_task(
                    task.task_id,
                    status="patched",
                    filename=apk.name,
                )
                if updated:
                    pq.put_device(updated)
        except Exception as exc:
            emit(
                normalize(exc),
                task=task,
                task_root=_task_root_for(task),
            )
        finally:
            pq.Q_PATCH.task_done()


def _device_loop() -> None:
    while True:
        task = pq.Q_DEVICE.get()
        serial = ""
        try:
            apk = _apk_path(task)
            signed = _signed_path(task)
            if apk is None or signed is None:
                _fail(task, "PATCH_MISSING", "patched artifacts missing", "device")
                continue
            package_name = package_name_from_apk(apk)
            if not package_name:
                _fail(task, "PREP_PACKAGE", "cannot resolve package", "device")
                continue
            adb_pool, _ = _pools()
            serial = adb_pool.acquire(
                config.ADB_SERIAL or None
            )
            queue_manager.update_task(
                task.task_id,
                status="on_device",
                adb_serial=serial,
            )
            with stage_scope("device"):
                task_root = config.WORKSPACE_ROOT / apk.stem
                run_device_stage(
                    task_root=task_root,
                    apk_path=apk,
                    signed_apk=signed,
                    package_name=package_name,
                    serial=serial,
                )
            updated = queue_manager.update_task(
                task.task_id,
                status="device_done",
                adb_serial=serial,
            )
            if updated:
                pq.put_extract(updated)
        except TimeoutError:
            _fail(task, "DEVICE_WAIT_TIMEOUT", "adb wait timeout", "device")
        except Exception as exc:
            emit(
                normalize(exc),
                task=task,
                task_root=_task_root_for(task),
            )
        finally:
            if serial:
                _pools()[0].release(serial)
            pq.Q_DEVICE.task_done()


def _extract_loop() -> None:
    while True:
        task = pq.Q_EXTRACT.get()
        held = False
        try:
            _pools()[1].acquire()
            held = True
            queue_manager.update_task(task.task_id, status="on_extract")
            task_root = _task_root_for(task)
            if task_root is None:
                _fail(task, "WORKSPACE_MISSING", "task workspace missing", "extract")
                continue
            filename = task.filename
            label = task.label or ""
            with stage_scope("extract"):
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
            updated = queue_manager.update_task(
                task.task_id, status="extract_done"
            )
            if held:
                _pools()[1].release()
                held = False
            if updated:
                pq.put_archive(updated)
        except TimeoutError:
            _fail(task, "OPENCODE_WAIT_TIMEOUT", "opencode wait timeout", "extract")
        except Exception as exc:
            emit(
                normalize(exc),
                task=task,
                task_root=_task_root_for(task),
            )
        finally:
            if held:
                _pools()[1].release()
            pq.Q_EXTRACT.task_done()


def _archive_loop() -> None:
    while True:
        task = pq.Q_ARCHIVE.get()
        filename = task.filename or ""
        try:
            task_root = _task_root_for(task)
            if task_root is None or not filename:
                _fail(task, "ARCHIVE_MISSING", "missing workspace/filename", "archive")
                continue
            task_key = Path(filename).stem
            label = task.label or ""
            with stage_scope("archive"):
                ensure_csv_after_agent(filename, 0)
                csv_path, text = wait_for_csv(
                    filename, timeout_sec=config.CSV_GRACE_SEC
                )
                status = classify_csv(text)
                body_text, session_id = clean_result_csv(text)
                if not session_id:
                    session_id = read_session_id_from_log(filename)
                if not session_id:
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
                    task.task_id,
                    status=status,
                    result_csv=str(archived),
                    session_id=session_id,
                    error=err_line,
                    buf_done_zip=queue_manager.buf_done_zip_for(str(archived)),
                )
                if updated is not None:
                    queue_manager.append_session_record(updated)
                layout = task_layout(task_root)
                export_path = layout["opencode_export"]
                meta = {
                    "task_id": task.task_id,
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
        except Exception as exc:
            emit(
                normalize(exc),
                task=task,
                task_root=_task_root_for(task),
            )
        finally:
            cleanup_download_apk(filename)
            pq.Q_ARCHIVE.task_done()


def recover_and_enqueue() -> None:
    """Apply recovery matrix and feed stage queues from DB active rows."""
    for task in task_store.list_active():
        status = task.status
        if status == "queued":
            pq.put_download(task)
        elif status == "downloaded":
            if _apk_path(task) is None:
                queue_manager.update_task(task.task_id, status="queued", filename="")
                fresh = queue_manager.get_task(task.task_id)
                if fresh:
                    pq.put_download(fresh)
            else:
                pq.put_patch(task)
        elif status == "patched":
            pq.put_device(task)
        elif status == "on_device":
            queue_manager.update_task(
                task.task_id,
                status="failed",
                error="PIPELINE_INTERRUPTED:on_device",
            )
        elif status == "device_done":
            pq.put_extract(task)
        elif status == "on_extract":
            queue_manager.update_task(
                task.task_id,
                status="failed",
                error="PIPELINE_INTERRUPTED:on_extract",
            )
        elif status == "extract_done":
            pq.put_archive(task)


def start_pipeline() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        ensure_buf_done_worker()
        for i in range(max(1, config.DOWNLOAD_WORKERS)):
            threading.Thread(
                target=_download_loop, name=f"dl-{i}", daemon=True
            ).start()
        for i in range(max(1, config.PATCH_WORKERS)):
            threading.Thread(
                target=_patch_loop, name=f"patch-{i}", daemon=True
            ).start()
        adb_pool, _ = _pools()
        # Extra waiters are fine: AdbPool serializes by device count.
        device_workers = max(2, len(adb_pool.refresh()) or 1, config.OPENCODE_SLOTS)
        for i in range(device_workers):
            threading.Thread(
                target=_device_loop, name=f"device-{i}", daemon=True
            ).start()
        for i in range(max(1, config.OPENCODE_SLOTS)):
            threading.Thread(
                target=_extract_loop, name=f"extract-{i}", daemon=True
            ).start()
        threading.Thread(
            target=_archive_loop, name="archive-0", daemon=True
        ).start()
        _write_heartbeat()
        threading.Thread(
            target=_heartbeat_loop, name="heartbeat", daemon=True
        ).start()
        recover_and_enqueue()
        _started = True
        _log.info(
            "pipeline started download=%s patch=%s device=%s opencode=%s",
            config.DOWNLOAD_WORKERS,
            config.PATCH_WORKERS,
            device_workers,
            config.OPENCODE_SLOTS,
        )
