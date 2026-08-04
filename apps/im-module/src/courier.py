from __future__ import annotations

import atexit
import logging
import signal
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import config
from channels.base import Channel
from inbox_writer import new_request_id, write_inbox_json
from ops_commands import parse_ops_command
from parser import parse_task_message
from task_ledger_query import run_ledger_query

_log = logging.getLogger(__name__)


@dataclass
class PendingJob:
    request_id: str
    chat_id: str
    source_file: str
    expected: int
    delivered_ids: set[str] = field(default_factory=set)

    @property
    def finished(self) -> bool:
        return len(self.delivered_ids) >= self.expected


class Courier:
    def __init__(self, channel: Channel):
        self._channel = channel
        self._jobs: dict[str, PendingJob] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._offline_announced = False
        self._core_fault_announced = False
        self._hooks_registered = False

    def start(self) -> None:
        self._register_lifecycle_hooks()
        threading.Thread(target=self._poll_loop, name="im-poll", daemon=True).start()
        self._announce(config.MSG_BOT_ONLINE)
        self._channel.start(self.on_message)

    def stop(self) -> None:
        self._announce_offline_once()
        self._stop.set()

    def _register_lifecycle_hooks(self) -> None:
        if self._hooks_registered:
            return
        self._hooks_registered = True

        def _on_exit() -> None:
            self._announce_offline_once()

        atexit.register(_on_exit)

        def _on_signal(signum, _frame) -> None:
            _log.info("signal %s received, shutting down", signum)
            self.stop()
            raise SystemExit(0)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _on_signal)
            except (ValueError, OSError):
                pass

    def _announce(self, text: str) -> None:
        chat_id = (config.ANNOUNCE_CHAT_ID or "").strip()
        if not chat_id:
            _log.warning("ANNOUNCE_CHAT_ID empty; skip announce: %s", text)
            return
        try:
            self._channel.reply_text(chat_id, text)
        except Exception:
            _log.exception("announce failed chat_id=%s text=%s", chat_id, text)

    def _announce_offline_once(self) -> None:
        if self._offline_announced:
            return
        self._offline_announced = True
        self._announce(config.MSG_BOT_OFFLINE)

    def on_message(self, chat_id: str, text: str) -> None:
        cmd = parse_ops_command(text)
        if cmd is not None:
            self._handle_ops(chat_id, cmd)
            return
        payload = parse_task_message(text)
        if payload is None:
            self._channel.reply_text(chat_id, f"unknown command.\n{config.OPS_TEMPLATE}")
            return
        self._enqueue_urls(chat_id, payload["get-texts"]["urls"])

    def _handle_ops(self, chat_id: str, cmd) -> None:
        result = run_ledger_query(cmd)
        self._channel.reply_text(chat_id, result.message)
        if not result.ok or result.file_path is None:
            return
        try:
            self._channel.send_file(chat_id, result.file_path)
        except NotImplementedError:
            self._channel.reply_text(
                chat_id,
                f"channel cannot send files; saved: {result.file_path}",
            )
        except Exception as exc:
            self._channel.reply_text(chat_id, f"send file failed: {exc}")

    def _enqueue_urls(
        self, chat_id: str, urls: list[str], *, ack: bool = True
    ) -> Path:
        payload = {"get-texts": {"urls": list(urls)}}
        request_id = new_request_id()
        path = write_inbox_json(config.INBOX_DIR, payload, request_id=request_id)
        job = PendingJob(
            request_id=request_id,
            chat_id=chat_id,
            source_file=path.name,
            expected=len(urls),
        )
        with self._lock:
            self._jobs[request_id] = job
        if ack:
            self._channel.reply_text(
                chat_id,
                f"已入队：{path.name}\nurls={len(urls)}",
            )
        _log.info("submitted %s chat=%s urls=%s", path.name, chat_id, len(urls))
        return path

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
                self._check_core_health()
            except Exception:
                _log.exception("poll tick failed")
            self._stop.wait(config.POLL_SEC)

    def _core_is_healthy(self) -> bool:
        path = Path(config.CORE_HEARTBEAT_PATH)
        if not path.is_file():
            return False
        age = time.time() - path.stat().st_mtime
        return age <= float(config.CORE_HEARTBEAT_STALE_SEC)

    def _check_core_health(self) -> None:
        healthy = self._core_is_healthy()
        if not healthy and not self._core_fault_announced:
            self._announce(config.MSG_CORE_DOWN)
            self._core_fault_announced = True
        elif healthy and self._core_fault_announced:
            self._announce(config.MSG_CORE_UP)
            self._core_fault_announced = False

    def _tick(self) -> None:
        with self._lock:
            jobs = [j for j in self._jobs.values() if not j.finished]
        for job in jobs:
            for done in _list_undelivered(job.source_file):
                task_id = str(done.get("task_id") or "")
                if not task_id or task_id in job.delivered_ids:
                    continue
                if self._deliver_done(job, done):
                    _mark_delivered(task_id)
                    with self._lock:
                        job.delivered_ids.add(task_id)
                        if job.finished:
                            _log.info(
                                "job complete %s delivered=%s",
                                job.source_file,
                                len(job.delivered_ids),
                            )

    def _deliver_done(self, job: PendingJob, done: dict) -> bool:
        st = str(done.get("status") or "")
        task_id = str(done.get("task_id") or "")
        label = str(done.get("label") or done.get("filename") or task_id)
        if st == "success":
            zip_path = Path(str(done.get("buf_done_zip") or ""))
            if not zip_path.is_file():
                age = time.time() - int(job.request_id.split("_")[0])
                if age < config.ZIP_WAIT_SEC:
                    return False
                self._channel.reply_text(
                    job.chat_id,
                    f"任务成功但结果文件超时未出现：{label} ({zip_path.name or '-'})",
                )
                return True
            try:
                self._channel.send_file(job.chat_id, zip_path)
                self._channel.reply_text(
                    job.chat_id, f"结果已发送：{zip_path.name} ({label})"
                )
            except Exception as exc:
                self._channel.reply_text(
                    job.chat_id, f"发送结果失败：{label}\n{exc}"
                )
            return True
        err = done.get("error") or st
        self._channel.reply_text(job.chat_id, f"任务结束：{label}\n{st}\n{err}")
        return True


def _list_undelivered(source_file: str) -> list[dict]:
    db = Path(config.TASKS_DB)
    if not db.is_file():
        return []
    name = Path(source_file).name
    uri = f"file:{db.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT task_id, status, label, filename, error, result_csv,
                   buf_done_zip, finished_at
            FROM tasks
            WHERE source_file=?
              AND status IN (
                'success','decrypt_failed','assets_missing',
                'abnormal_exit','failed','timeout'
              )
              AND (im_delivered_at IS NULL OR im_delivered_at='')
            ORDER BY finished_at ASC, updated_at ASC
            """,
            (name,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _mark_delivered(task_id: str) -> None:
    db = Path(config.TASKS_DB)
    if not db.is_file():
        return
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = sqlite3.connect(str(db), timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE tasks SET im_delivered_at=?, updated_at=? WHERE task_id=?",
            (now, now, task_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
