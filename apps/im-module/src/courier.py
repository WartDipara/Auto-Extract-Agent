"""Channel-agnostic courier: inbox submit, queue watch, buf_done delivery."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import config
from channels.base import Channel
from inbox_writer import new_request_id, write_inbox_json
from parser import parse_task_message
from queue_reader import find_by_source, read_queue_status

_log = logging.getLogger(__name__)


@dataclass
class PendingJob:
    request_id: str
    chat_id: str
    source_file: str
    delivered: bool = False


class Courier:
    def __init__(self, channel: Channel):
        self._channel = channel
        self._jobs: dict[str, PendingJob] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._poll_loop, name="im-poll", daemon=True).start()
        self._channel.start(self.on_message)

    def stop(self) -> None:
        self._stop.set()

    def on_message(self, chat_id: str, text: str) -> None:
        payload = parse_task_message(text)
        if payload is None:
            self._channel.reply_text(chat_id, f"JSON 无效。\n{config.OPS_TEMPLATE}")
            return
        request_id = new_request_id()
        path = write_inbox_json(config.INBOX_DIR, payload, request_id=request_id)
        job = PendingJob(
            request_id=request_id,
            chat_id=chat_id,
            source_file=path.name,
        )
        with self._lock:
            self._jobs[request_id] = job
        self._channel.reply_text(
            chat_id,
            f"已入队：{path.name}\nurls={len(payload['get-texts']['urls'])}",
        )
        _log.info("submitted %s chat=%s", path.name, chat_id)

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                _log.exception("poll tick failed")
            self._stop.wait(config.POLL_SEC)

    def _tick(self) -> None:
        status = read_queue_status(config.QUEUE_STATUS_FILE)
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job.delivered:
                continue
            active, done = find_by_source(status, job.source_file)
            if active is not None:
                continue
            if done is None:
                continue
            st = str(done.get("status") or "")
            if st == "success":
                zip_path = Path(str(done.get("buf_done_zip") or ""))
                if not zip_path.is_file():
                    age = time.time() - int(job.request_id.split("_")[0])
                    if age < config.ZIP_WAIT_SEC:
                        continue
                    self._channel.reply_text(
                        job.chat_id,
                        f"任务成功但 zip 超时未出现：{zip_path.name or '-'}",
                    )
                    self._mark_done(job.request_id)
                    continue
                try:
                    self._channel.send_file(job.chat_id, zip_path)
                    self._channel.reply_text(job.chat_id, f"结果已发送：{zip_path.name}")
                except Exception as exc:
                    self._channel.reply_text(job.chat_id, f"发送 zip 失败：{exc}")
                self._mark_done(job.request_id)
                continue
            err = done.get("error") or st
            self._channel.reply_text(job.chat_id, f"任务结束：{st}\n{err}")
            self._mark_done(job.request_id)

    def _mark_done(self, request_id: str) -> None:
        with self._lock:
            job = self._jobs.get(request_id)
            if job:
                job.delivered = True
