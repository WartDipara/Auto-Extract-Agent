from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

import config
import queue_manager
from errors.model import ErrorInfo
from shared.archive_contract import has_stop, mark_stop, read_meta, write_meta

_log = logging.getLogger(__name__)

_SINKS: list[ErrorSink] = []


class ErrorSink(Protocol):
    name: str

    def emit(self, info: ErrorInfo, **ctx: Any) -> None: ...


def register_sink(sink: ErrorSink) -> None:
    _SINKS.append(sink)
    _log.info("error sink registered: %s", sink.name)


def emit(info: ErrorInfo, **ctx: Any) -> None:
    for sink in _SINKS:
        try:
            sink.emit(info, **ctx)
        except Exception:
            _log.exception("error sink failed: %s", sink.name)


class LogSink:
    name = "log"

    def emit(self, info: ErrorInfo, **ctx: Any) -> None:
        task = ctx.get("task")
        task_id = getattr(task, "task_id", "") or ctx.get("task_id", "")
        line = info.to_line()
        if info.code == "UNEXPECTED":
            _log.error("task %s %s", task_id, line, exc_info=True)
        elif info.code == "EXTRACT_STOPPED":
            _log.warning("task %s %s", task_id, line)
        else:
            _log.error("task %s %s", task_id, line)


class QueueSink:
    name = "queue"

    def emit(self, info: ErrorInfo, **ctx: Any) -> None:
        task = ctx.get("task")
        task_id = getattr(task, "task_id", None) or ctx.get("task_id")
        if not task_id:
            return
        try:
            expected = getattr(task, "run_gen", None) if task is not None else None
            kwargs = {
                "status": info.status,
                "error": info.to_line(),
            }
            if expected is not None:
                kwargs["expected_run_gen"] = int(expected or 0)
            queue_manager.update_task(task_id, **kwargs)
        except Exception:
            # Keep worker loops alive; leave an operational breadcrumb.
            _log.exception(
                "QueueSink update_task failed task_id=%s status=%s error=%s",
                task_id,
                info.status,
                info.to_line(),
            )
            try:
                path = config.SERVICE_LOG
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as fp:
                    fp.write(
                        f"QueueSinkFail task={task_id} status={info.status} "
                        f"{info.to_line()}\n"
                    )
            except Exception:
                _log.exception("QueueSink service.log write failed")


class MetaSink:
    name = "meta"

    def emit(self, info: ErrorInfo, **ctx: Any) -> None:
        task_root = ctx.get("task_root")
        if not task_root:
            return
        root = Path(task_root)
        if not root.is_dir():
            return
        payload = read_meta(root) or {}
        task = ctx.get("task")
        if task is not None:
            payload.setdefault("task_id", getattr(task, "task_id", ""))
            payload.setdefault("url", getattr(task, "url", ""))
            payload.setdefault("filename", getattr(task, "filename", ""))
            payload.setdefault("label", getattr(task, "label", ""))
        payload["status"] = info.status
        payload["error"] = info.to_line()
        payload["error_info"] = info.to_dict()
        write_meta(root, payload)


class StopMarkerSink:
    """Ensure .stop exists when extract was interrupted (purge can reclaim)."""

    name = "stop_marker"

    def emit(self, info: ErrorInfo, **ctx: Any) -> None:
        if info.code != "EXTRACT_STOPPED":
            return
        task = ctx.get("task")
        filename = getattr(task, "filename", "") or ""
        task_key = Path(filename).stem if filename else ""
        if not task_key:
            return
        root = config.WORKSPACE_ROOT / task_key
        if root.is_dir() and not has_stop(root):
            mark_stop(root)
