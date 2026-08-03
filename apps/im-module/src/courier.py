"""Channel-agnostic courier: inbox submit, queue watch, buf_done delivery."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import config
from channels.base import Channel
from inbox_writer import new_request_id, write_inbox_json
from parser import parse_task_message
from queue_reader import list_by_source, read_queue_status
from sheet_sync import commit_sync, is_sync_command, sync_from_bitable

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

    def start(self) -> None:
        threading.Thread(target=self._poll_loop, name="im-poll", daemon=True).start()
        self._channel.start(self.on_message)

    def stop(self) -> None:
        self._stop.set()

    def on_message(self, chat_id: str, text: str) -> None:
        if is_sync_command(text):
            self._handle_sheet_sync(chat_id)
            return

        payload = parse_task_message(text)
        if payload is None:
            self._channel.reply_text(chat_id, f"无法识别指令。\n{config.OPS_TEMPLATE}")
            return
        self._enqueue_urls(chat_id, payload["get-texts"]["urls"])

    def _handle_sheet_sync(self, chat_id: str) -> None:
        result = sync_from_bitable()
        if result.error:
            self._channel.reply_text(chat_id, result.summary_text())
            return
        if not result.queued_urls:
            commit_sync(result)
            self._channel.reply_text(chat_id, result.summary_text())
            return

        batch = max(1, int(config.SHEET_SYNC_BATCH_SIZE))
        chunks = [
            result.queued_urls[i : i + batch]
            for i in range(0, len(result.queued_urls), batch)
        ]
        names: list[str] = []
        for urls in chunks:
            path = self._enqueue_urls(chat_id, urls, ack=False)
            names.append(path.name)
        commit_sync(result)
        summary = result.summary_text()
        summary += f"\n已写入 inbox：{', '.join(names)}"
        self._channel.reply_text(chat_id, summary)
        _log.info(
            "sheet sync chat=%s queued=%s files=%s",
            chat_id,
            result.queued,
            names,
        )

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
            except Exception:
                _log.exception("poll tick failed")
            self._stop.wait(config.POLL_SEC)

    def _tick(self) -> None:
        status = read_queue_status(config.QUEUE_STATUS_FILE)
        with self._lock:
            jobs = [j for j in self._jobs.values() if not j.finished]
        for job in jobs:
            _actives, dones = list_by_source(status, job.source_file)
            for done in dones:
                task_id = str(done.get("task_id") or "")
                if not task_id or task_id in job.delivered_ids:
                    continue
                if self._deliver_done(job, done):
                    with self._lock:
                        job.delivered_ids.add(task_id)
                        if job.finished:
                            _log.info(
                                "job complete %s delivered=%s",
                                job.source_file,
                                len(job.delivered_ids),
                            )

    def _deliver_done(self, job: PendingJob, done: dict) -> bool:
        """Handle one finished task. True = consumed (do not retry)."""
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
