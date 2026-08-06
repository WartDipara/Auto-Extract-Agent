from __future__ import annotations

import atexit
import logging
import signal
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import config
from announce_chat import resolve_announce_chat, save_learned_chat
from channels.base import Channel, IncomingChat
from inbox_writer import new_request_id, write_inbox_json
from ops_commands import parse_ops_command
from parser import parse_task_message
from task_ledger_query import run_ledger_query

_log = logging.getLogger(__name__)


def _terminal_for(spec) -> tuple[str, ...]:
    return tuple(sorted(spec.terminal_statuses))


class Courier:
    def __init__(self, channel: Channel):
        self._channel = channel
        self._stop = threading.Event()
        self._online_announced = False
        self._offline_announced = False
        self._core_fault_announced = False
        self._hooks_registered = False
        self._missing_chat_warned: set[str] = set()
        self._deliver_fail_warned: set[str] = set()

    def start(self) -> None:
        self._register_lifecycle_hooks()
        # Online first, then core health — poll must not race ahead of intro.
        self._announce_online()
        threading.Thread(target=self._poll_loop, name="im-poll", daemon=True).start()
        try:
            self._channel.start(self.on_message)
        except KeyboardInterrupt:
            _log.info("im-module stopped")
        finally:
            self.stop()

    def stop(self) -> None:
        self._announce_offline_once()
        self._stop.set()
        stopper = getattr(self._channel, "stop", None)
        if callable(stopper):
            stopper()

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
            # DingTalk SDK stream loops break on KeyboardInterrupt only.
            raise KeyboardInterrupt

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _on_signal)
            except (ValueError, OSError):
                pass

    def _announce(self, text: str) -> bool:
        chat_id = resolve_announce_chat(
            pinned=config.ANNOUNCE_CHAT_ID,
            state_path=Path(config.ANNOUNCE_CHAT_STATE),
        )
        if not chat_id:
            _log.info(
                "announce skipped (no chat yet); "
                "will learn from first @mention unless ANNOUNCE_CHAT_ID is pinned"
            )
            return False
        try:
            self._channel.reply_text(chat_id, text)
            return True
        except Exception:
            _log.exception("announce failed chat_id=%s text=%s", chat_id, text)
            return False

    def _announce_online(self) -> None:
        if self._online_announced:
            return
        text = f"{config.pick_bot_online()}\n\n{config.OPS_TEMPLATE}"
        if self._announce(text):
            self._online_announced = True
            self._check_core_health()

    def _remember_chat(self, chat_id: str) -> None:
        if (config.ANNOUNCE_CHAT_ID or "").strip():
            return
        changed = save_learned_chat(Path(config.ANNOUNCE_CHAT_STATE), chat_id)
        if changed and not self._online_announced:
            self._announce_online()

    def _announce_offline_once(self) -> None:
        if self._offline_announced:
            return
        self._offline_announced = True
        self._announce(config.pick_bot_offline())

    def on_message(self, incoming: IncomingChat) -> None:
        chat_id = incoming.chat_id
        text = incoming.text
        at_ids = [incoming.sender_id] if incoming.sender_id else None
        self._remember_chat(chat_id)
        cmd = parse_ops_command(text)
        if cmd is not None:
            if cmd.kind == "greet":
                self._channel.reply_text(
                    chat_id, config.pick_greet(), at_user_ids=at_ids
                )
                return
            self._handle_ops(chat_id, cmd, at_user_ids=at_ids)
            return
        payload = parse_task_message(text)
        if payload is None:
            self._channel.reply_text(
                chat_id,
                f"{config.BOT_NAME}没看懂这条指令。\n{config.OPS_TEMPLATE}",
                at_user_ids=at_ids,
            )
            return
        self._enqueue_urls(
            chat_id,
            payload["get-texts"]["urls"],
            sender_id=incoming.sender_id,
            at_user_ids=at_ids,
        )

    def _handle_ops(self, chat_id: str, cmd, *, at_user_ids=None) -> None:
        result = run_ledger_query(cmd)
        self._channel.reply_text(
            chat_id, result.message, at_user_ids=at_user_ids
        )
        if not result.ok or result.file_path is None:
            return
        try:
            self._channel.send_file(chat_id, result.file_path)
        except NotImplementedError:
            self._channel.reply_text(
                chat_id,
                f"channel cannot send files; saved: {result.file_path}",
                at_user_ids=at_user_ids,
            )
        except Exception as exc:
            self._channel.reply_text(
                chat_id, f"send file failed: {exc}", at_user_ids=at_user_ids
            )

    def _enqueue_urls(
        self,
        chat_id: str,
        urls: list[str],
        *,
        sender_id: str = "",
        at_user_ids=None,
        ack: bool = True,
    ) -> Path:
        route = config.INBOX_ROUTE
        body = {
            "urls": list(urls),
            "im_chat_id": chat_id,
        }
        if sender_id:
            body["im_sender_id"] = sender_id
        payload = {route: body}
        request_id = new_request_id()
        path = write_inbox_json(config.INBOX_DIR, payload, request_id=request_id)
        if ack:
            self._channel.reply_text(
                chat_id,
                self._enqueue_ack_text(path.name, len(urls)),
                at_user_ids=at_user_ids,
            )
        _log.info(
            "submitted %s chat=%s sender=%s urls=%s",
            path.name,
            chat_id,
            sender_id or "-",
            len(urls),
        )
        return path

    def _enqueue_ack_text(self, filename: str, url_count: int) -> str:
        base = f"已入队：{filename}\nurls={url_count}"
        if self._core_is_healthy(stale_sec=config.CORE_SUBMIT_STALE_SEC):
            return base
        # Same group already heard via this ack — suppress later poll broadcast.
        first = not self._core_fault_announced
        self._core_fault_announced = True
        note = (
            config.MSG_ENQUEUE_CORE_DEFERRED_FIRST
            if first
            else config.MSG_ENQUEUE_CORE_DEFERRED_AGAIN
        )
        return f"{base}\n{note}"

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
                self._check_core_health()
            except Exception:
                _log.exception("poll tick failed")
            self._stop.wait(config.POLL_SEC)

    def _core_is_healthy(self, *, stale_sec: float | None = None) -> bool:
        limit = (
            float(config.CORE_HEARTBEAT_STALE_SEC)
            if stale_sec is None
            else float(stale_sec)
        )
        paths = [Path(config.CORE_HEARTBEAT_PATH)]
        paths.extend(Path(spec.heartbeat_path) for spec in config.MODULES[1:])
        now = time.time()
        for path in paths:
            if not path.is_file():
                return False
            if (now - path.stat().st_mtime) > limit:
                return False
        return True

    def _check_core_health(self) -> None:
        if not self._online_announced:
            return
        healthy = self._core_is_healthy()
        if not healthy and not self._core_fault_announced:
            self._announce(config.pick_core_down())
            self._core_fault_announced = True
        elif healthy and self._core_fault_announced:
            self._announce(config.pick_core_up())
            self._core_fault_announced = False

    def _tick(self) -> None:
        for done in _list_undelivered():
            task_id = str(done.get("task_id") or "")
            if not task_id:
                continue
            chat_id = _resolve_delivery_chat(done)
            if not chat_id:
                if task_id not in self._missing_chat_warned:
                    self._missing_chat_warned.add(task_id)
                    _log.warning(
                        "skip deliver %s: no im_chat_id and no announce chat",
                        task_id,
                    )
                continue
            if self._deliver_done(chat_id, done):
                _mark_delivered(
                    task_id,
                    table=str(done.get("_tasks_table") or config.TASKS_TABLE),
                )
                self._missing_chat_warned.discard(task_id)

    def _deliver_done(self, chat_id: str, done: dict) -> bool:
        st = str(done.get("status") or "")
        task_id = str(done.get("task_id") or "")
        label = str(done.get("label") or done.get("filename") or task_id)
        sender = str(done.get("im_sender_id") or "").strip()
        at_ids = [sender] if sender else None
        if st == "success":
            zip_path = Path(str(done.get("buf_done_zip") or ""))
            if not zip_path.is_file():
                if _age_since_finish_sec(done) < config.ZIP_WAIT_SEC:
                    return False
                self._channel.reply_text(
                    chat_id,
                    f"任务成功但结果文件超时未出现：{label} ({zip_path.name or '-'})",
                    at_user_ids=at_ids,
                )
                return True
            try:
                self._channel.send_file(chat_id, zip_path)
                self._channel.reply_text(
                    chat_id,
                    f"结果已发送：{zip_path.name} ({label})",
                    at_user_ids=at_ids,
                )
                self._deliver_fail_warned.discard(task_id)
                return True
            except Exception as exc:
                _log.exception("deliver file failed task_id=%s", task_id)
                if task_id not in self._deliver_fail_warned:
                    self._deliver_fail_warned.add(task_id)
                    try:
                        self._channel.reply_text(
                            chat_id,
                            f"发送结果失败：{label}\n{exc}",
                            at_user_ids=at_ids,
                        )
                    except Exception:
                        _log.exception(
                            "deliver failure notice failed task_id=%s", task_id
                        )
                return False
        err = done.get("error") or st
        self._channel.reply_text(
            chat_id,
            f"任务结束：{label}\n{st}\n{err}",
            at_user_ids=at_ids,
        )
        return True


def _resolve_delivery_chat(done: dict) -> str:
    chat = str(done.get("im_chat_id") or "").strip()
    if chat:
        return chat
    return resolve_announce_chat(
        pinned=config.ANNOUNCE_CHAT_ID,
        state_path=Path(config.ANNOUNCE_CHAT_STATE),
    )


def _age_since_finish_sec(done: dict) -> float:
    raw = str(done.get("finished_at") or done.get("updated_at") or "").strip()
    if not raw:
        return 0.0
    try:
        normalized = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, time.time() - parsed.timestamp())
    except ValueError:
        return 0.0


def _list_undelivered() -> list[dict]:
    db = Path(config.TASKS_DB)
    if not db.is_file():
        return []
    uri = f"file:{db.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    out: list[dict] = []
    try:
        for spec in config.MODULES:
            terminal = _terminal_for(spec)
            if not terminal:
                continue
            placeholders = ",".join("?" * len(terminal))
            sql = f"""
                SELECT task_id, status, label, filename, error, result_csv,
                       buf_done_zip, finished_at, updated_at, source_file
                       {{extra}}
                FROM {spec.tasks_table}
                WHERE status IN ({placeholders})
                  AND (im_delivered_at IS NULL OR im_delivered_at='')
                ORDER BY finished_at ASC, updated_at ASC
                """
            try:
                rows = conn.execute(
                    sql.format(extra=", im_chat_id, im_sender_id"),
                    terminal,
                ).fetchall()
            except sqlite3.OperationalError:
                try:
                    rows = conn.execute(
                        sql.format(extra=", im_chat_id"),
                        terminal,
                    ).fetchall()
                except sqlite3.OperationalError:
                    try:
                        rows = conn.execute(
                            sql.format(extra=""),
                            terminal,
                        ).fetchall()
                    except sqlite3.OperationalError:
                        _log.warning(
                            "undelivered query skipped table=%s", spec.tasks_table
                        )
                        continue
            for row in rows:
                item = dict(row)
                item.setdefault("im_chat_id", "")
                item.setdefault("im_sender_id", "")
                item["_module_id"] = spec.module_id
                item["_tasks_table"] = spec.tasks_table
                out.append(item)
        return out
    finally:
        conn.close()


def _mark_delivered(task_id: str, *, table: str | None = None) -> None:
    db = Path(config.TASKS_DB)
    if not db.is_file():
        return
    tbl = table or config.TASKS_TABLE
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = sqlite3.connect(str(db), timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            f"UPDATE {tbl} SET im_delivered_at=?, updated_at=? WHERE task_id=?",
            (now, now, task_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
