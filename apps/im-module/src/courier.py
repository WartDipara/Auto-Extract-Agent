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
from announce_chat import add_announce_chat, resolve_announce_chats
from channels.base import Channel, IncomingChat
from delivery_audit import append_delivery_event
from inbox_writer import new_request_id, write_inbox_json
from ops_commands import parse_ops_command
from parser import parse_task_message
from pending_inbox import (
    add_pending,
    bump_resubmit,
    list_pending,
    mark_exhausted,
    remove_pending,
)
from task_ledger_query import run_ledger_query

_log = logging.getLogger(__name__)
_DELIVER_ERR_MAX = 400


def _terminal_for(spec) -> tuple[str, ...]:
    return tuple(sorted(spec.terminal_statuses))


def _clip_err(text: str) -> str:
    s = " ".join(str(text or "").split())
    if len(s) <= _DELIVER_ERR_MAX:
        return s
    return s[: _DELIVER_ERR_MAX - 1] + "…"


def _user_label(done_or_label) -> str:
    if isinstance(done_or_label, dict):
        raw = done_or_label.get("label") or done_or_label.get("filename") or ""
    else:
        raw = done_or_label
    name = " ".join(str(raw or "未命名").split()) or "未命名"
    if len(name) > 40:
        name = name[:39] + "…"
    return name


def _user_task_card(title: str, *, label: str, task_id: str, extra: list[str] | None = None) -> str:
    lines = [f"【{label}】{title}", f"任务号：{task_id or '-'}"]
    if extra:
        lines.extend(extra)
    return "\n".join(lines)


def _non_retryable_deliver_error(exc: BaseException | str) -> bool:
    text = str(exc or "").lower()
    keys = (
        "missing im_chat_id",
        "file too large",
        "too large",
        "20mb",
        "unsupported",
        "not supported",
        "suffix",
        "invalid file type",
        "file type",
    )
    return any(k in text for k in keys)


def _load_file_sent() -> set[str]:
    path = Path(getattr(config, "FILE_SENT_STATE", "") or "")
    if not path.is_file():
        return set()
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(x) for x in data if str(x).strip()}
        if isinstance(data, dict) and isinstance(data.get("task_ids"), list):
            return {str(x) for x in data["task_ids"] if str(x).strip()}
    except Exception:
        _log.exception("load file_sent state failed")
    return set()


def _save_file_sent(task_ids: set[str]) -> None:
    path = Path(getattr(config, "FILE_SENT_STATE", "") or "")
    if not path:
        return
    try:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"task_ids": sorted(task_ids)}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        _log.exception("save file_sent state failed")


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
        self._zip_timeout_warned: set[str] = set()
        self._pending_exhausted_warned: set[str] = set()
        self._deliver_attempts: dict[str, int] = {}
        self._file_sent_ok: set[str] = _load_file_sent()

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
        """Broadcast lifecycle notice to all known groups (not task delivery)."""
        chat_ids = resolve_announce_chats(
            pinned=config.ANNOUNCE_CHAT_ID,
            state_path=Path(config.ANNOUNCE_CHAT_STATE),
        )
        if not chat_ids:
            _log.info(
                "announce skipped (no chat yet); "
                "will learn from @mentions or use ANNOUNCE_CHAT_ID"
            )
            return False
        ok = False
        for chat_id in chat_ids:
            try:
                # Broadcast only — never @ a user on online/offline/fault.
                self._channel.reply_text(chat_id, text, at_user_ids=[])
                ok = True
            except Exception:
                _log.exception("announce failed chat_id=%s text=%s", chat_id, text)
        return ok

    def _announce_online(self) -> None:
        if self._online_announced:
            return
        text = f"{config.pick_bot_online()}\n\n{config.OPS_TEMPLATE}"
        if self._announce(text):
            self._online_announced = True
            self._check_core_health()

    def _remember_chat(self, chat_id: str) -> None:
        """Accumulate groups for lifecycle broadcast; never used for task results."""
        added = add_announce_chat(Path(config.ANNOUNCE_CHAT_STATE), chat_id)
        if not added:
            return
        if not self._online_announced:
            self._announce_online()
            return
        # New group after bot already online — greet this chat only.
        text = f"{config.pick_bot_online()}\n\n{config.OPS_TEMPLATE}"
        try:
            self._channel.reply_text(chat_id, text, at_user_ids=[])
        except Exception:
            _log.exception("announce online to new chat failed chat_id=%s", chat_id)

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
            self._handle_ops(
                chat_id,
                cmd,
                sender_id=incoming.sender_id,
                at_user_ids=at_ids,
            )
            return
        payload = parse_task_message(text)
        if payload is None:
            self._channel.reply_text(
                chat_id,
                "未能识别该指令。发送 help 查看用法；"
                "或 query … / export table …；"
                "提交任务请直接发 APK 链接。",
                at_user_ids=at_ids,
            )
            return
        self._enqueue_urls(
            chat_id,
            payload["get-texts"]["urls"],
            sender_id=incoming.sender_id,
            at_user_ids=at_ids,
        )

    def _handle_ops(
        self, chat_id: str, cmd, *, sender_id: str = "", at_user_ids=None
    ) -> None:
        result = run_ledger_query(cmd, sender_id=sender_id)
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
                "表格已生成，但当前通道不支持发文件，请联系管理员取回。",
                at_user_ids=at_user_ids,
            )
        except Exception:
            self._channel.reply_text(
                chat_id,
                "表格已生成，但发送失败，请稍后重试 export table。",
                at_user_ids=at_user_ids,
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
        filename = f"im_{request_id}.json"
        path = (Path(config.INBOX_DIR) / filename).resolve()
        state = Path(config.PENDING_INBOX_STATE)
        # Track first so a crash after inbox write still has urls to rewrite.
        add_pending(
            state,
            filename=filename,
            inbox_path=str(path),
            chat_id=chat_id,
            sender_id=sender_id,
            urls=list(urls),
            route=route,
        )
        try:
            path = write_inbox_json(
                config.INBOX_DIR, payload, request_id=request_id
            )
        except Exception:
            remove_pending(state, filename)
            raise
        if ack:
            self._channel.reply_text(
                chat_id,
                self._enqueue_ack_text(path.name, len(urls)),
                at_user_ids=at_user_ids,
            )
        _log.info(
            "submitted %s path=%s chat=%s sender=%s urls=%s",
            path.name,
            path,
            chat_id,
            sender_id or "-",
            len(urls),
        )
        return path

    def _enqueue_ack_text(self, _filename: str, url_count: int) -> str:
        base = (
            f"已登记，共 {url_count} 条链接\n"
            "处理完成后结果将发回本群。"
        )
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
                self._reconcile_pending_inbox()
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
            # Core just recovered: rewrite any vanished inbox files now.
            self._reconcile_pending_inbox(force_resubmit=True)

    def _reconcile_pending_inbox(self, *, force_resubmit: bool = False) -> None:
        """Ensure deferred inbox files still exist until Module A accepts them."""
        state = Path(config.PENDING_INBOX_STATE)
        pending = list_pending(state)
        if not pending:
            return
        core_ok = self._core_is_healthy()
        for item in pending:
            filename = str(item.get("filename") or "").strip()
            if not filename:
                continue
            if item.get("exhausted"):
                continue
            if _source_accepted(filename) or _source_processed_ok(filename):
                remove_pending(state, filename)
                self._pending_exhausted_warned.discard(filename)
                continue
            if _source_rejected(filename):
                self._notify_pending_terminal(
                    item,
                    "入队未受理，请检查链接或格式后重新提交。",
                )
                remove_pending(state, filename)
                continue
            urls = [u for u in (item.get("urls") or []) if str(u).strip()]
            # Same job already running under another inbox filename — do not resubmit.
            if urls and _urls_already_active(urls):
                _log.info(
                    "pending inbox cleared; urls already active file=%s",
                    filename,
                )
                remove_pending(state, filename)
                self._pending_exhausted_warned.discard(filename)
                continue
            path = Path(str(item.get("inbox_path") or "")).expanduser()
            if not path.is_absolute():
                path = Path(config.INBOX_DIR) / filename
            if path.is_file():
                if core_ok and (
                    force_resubmit or _inbox_file_stale(path)
                ):
                    try:
                        path.touch()
                    except OSError:
                        _log.exception(
                            "touch pending inbox failed file=%s", filename
                        )
                continue
            # File missing before core accepted it — rewrite when core is up.
            if not core_ok and not force_resubmit:
                _log.warning(
                    "pending inbox missing while core down file=%s", filename
                )
                continue
            if not urls:
                remove_pending(state, filename)
                continue
            resubmits = int(item.get("resubmit_count") or 0)
            if resubmits >= int(config.PENDING_INBOX_RESUBMIT_MAX):
                _log.error(
                    "pending inbox resubmit exhausted file=%s", filename
                )
                mark_exhausted(state, filename)
                self._notify_pending_terminal(
                    item,
                    "入队自动重试已达上限，请重新提交链接。",
                )
                continue
            route = str(item.get("route") or config.INBOX_ROUTE).strip()
            chat_id = str(item.get("chat_id") or "").strip()
            sender_id = str(item.get("sender_id") or "").strip()
            body = {"urls": urls, "im_chat_id": chat_id}
            if sender_id:
                body["im_sender_id"] = sender_id
            request_id = (
                filename[3:-5]
                if filename.startswith("im_") and filename.endswith(".json")
                else new_request_id()
            )
            try:
                written = write_inbox_json(
                    config.INBOX_DIR,
                    {route: body},
                    request_id=request_id,
                )
            except Exception:
                _log.exception("pending inbox rewrite failed file=%s", filename)
                continue
            bump_resubmit(state, filename)
            _log.warning(
                "pending inbox rewritten file=%s path=%s",
                filename,
                written,
            )
            if chat_id:
                try:
                    at_ids = [sender_id] if sender_id else None
                    self._channel.reply_text(
                        chat_id,
                        "处理服务已恢复，已登记任务将继续处理。",
                        at_user_ids=at_ids,
                    )
                except Exception:
                    _log.exception(
                        "pending inbox rewrite notice failed file=%s", filename
                    )

    def _notify_pending_terminal(self, item: dict, text: str) -> None:
        filename = str(item.get("filename") or "").strip()
        if not filename or filename in self._pending_exhausted_warned:
            return
        self._pending_exhausted_warned.add(filename)
        chat_id = str(item.get("chat_id") or "").strip()
        sender_id = str(item.get("sender_id") or "").strip()
        if not chat_id:
            return
        try:
            self._channel.reply_text(
                chat_id,
                text,
                at_user_ids=[sender_id] if sender_id else None,
            )
        except Exception:
            _log.exception("pending terminal notice failed file=%s", filename)

    def _max_deliver_attempts(self) -> int:
        return max(1, int(getattr(config, "DELIVER_MAX_ATTEMPTS", 10)))

    def _bump_attempt(self, task_id: str) -> int:
        n = self._deliver_attempts.get(task_id, 0) + 1
        self._deliver_attempts[task_id] = n
        return n

    def _clear_attempt(self, task_id: str) -> None:
        self._deliver_attempts.pop(task_id, None)
        self._missing_chat_warned.discard(task_id)
        self._deliver_fail_warned.discard(task_id)
        self._zip_timeout_warned.discard(task_id)

    def _remember_file_sent(self, task_id: str) -> None:
        if task_id in self._file_sent_ok:
            return
        self._file_sent_ok.add(task_id)
        _save_file_sent(self._file_sent_ok)

    def _forget_file_sent(self, task_id: str) -> None:
        if task_id not in self._file_sent_ok:
            return
        self._file_sent_ok.discard(task_id)
        _save_file_sent(self._file_sent_ok)

    def _abandon_delivery(
        self,
        done: dict,
        *,
        chat_id: str,
        reason: str,
        notify: bool = True,
    ) -> bool:
        task_id = str(done.get("task_id") or "")
        table = str(done.get("_tasks_table") or config.TASKS_TABLE)
        label = _user_label(done)
        sender = str(done.get("im_sender_id") or "").strip()
        at_ids = [sender] if sender else None
        err = f"abandoned:{reason}"
        if notify and chat_id:
            try:
                self._channel.reply_text(
                    chat_id,
                    _user_task_card(
                        "结果未能回传",
                        label=label,
                        task_id=task_id,
                        extra=["说明：请稍后重新提交，或联系管理员排查。"],
                    ),
                    at_user_ids=at_ids,
                )
            except Exception:
                _log.exception("abandon notice failed task_id=%s", task_id)
        try:
            _mark_delivered(task_id, table=table, deliver_error=err)
        except Exception:
            _log.exception("abandon mark_delivered failed task_id=%s", task_id)
            _set_deliver_error(task_id, err, table=table)
            return False
        self._audit(
            done,
            chat_id=chat_id,
            channel="-",
            outcome="abandoned",
            error=err,
        )
        self._clear_attempt(task_id)
        self._forget_file_sent(task_id)
        return True

    def _tick(self) -> None:
        for done in _list_undelivered():
            task_id = str(done.get("task_id") or "")
            if not task_id:
                continue
            table = str(done.get("_tasks_table") or config.TASKS_TABLE)
            chat_id = _resolve_delivery_chat(done)
            if not chat_id:
                if task_id not in self._missing_chat_warned:
                    self._missing_chat_warned.add(task_id)
                    _log.warning(
                        "abandon deliver %s: missing im_chat_id (fail-closed)",
                        task_id,
                    )
                    self._audit(
                        done,
                        chat_id="",
                        channel="-",
                        outcome="missing_im_chat_id",
                        error="im_chat_id empty; refuse announce fallback",
                    )
                self._abandon_delivery(
                    done,
                    chat_id="",
                    reason="missing im_chat_id",
                    notify=False,
                )
                continue
            try:
                if self._deliver_done(chat_id, done):
                    self._clear_attempt(task_id)
            except Exception as exc:
                _log.exception("deliver tick failed task_id=%s", task_id)
                _set_deliver_error(task_id, str(exc), table=table)

    def _audit(
        self,
        done: dict,
        *,
        chat_id: str,
        channel: str,
        outcome: str,
        error: str = "",
    ) -> None:
        append_delivery_event(
            Path(config.DELIVERY_AUDIT_PATH),
            {
                "task_id": str(done.get("task_id") or ""),
                "module": str(done.get("_module_id") or ""),
                "chat_id": chat_id,
                "sender_id": str(done.get("im_sender_id") or ""),
                "status": str(done.get("status") or ""),
                "channel": channel,
                "outcome": outcome,
                "error": error,
            },
        )

    def _deliver_done(self, chat_id: str, done: dict) -> bool:
        st = str(done.get("status") or "")
        task_id = str(done.get("task_id") or "")
        table = str(done.get("_tasks_table") or config.TASKS_TABLE)
        label = _user_label(done)
        sender = str(done.get("im_sender_id") or "").strip()
        at_ids = [sender] if sender else None
        max_attempts = self._max_deliver_attempts()

        if st == "success":
            zip_path = Path(str(done.get("buf_done_zip") or ""))
            if task_id in self._file_sent_ok:
                # File already sent earlier; only retry mark / text.
                try:
                    self._channel.reply_text(
                        chat_id,
                        _user_task_card(
                            "处理完成，结果已发到本群",
                            label=label,
                            task_id=task_id,
                            extra=[
                                f"文件：{zip_path.name or '-'}",
                                "解压密码可用 query password 查询。",
                            ],
                        ),
                        at_user_ids=at_ids,
                    )
                    text_err = ""
                except Exception as exc:
                    text_err = _clip_err(str(exc))
                try:
                    _mark_delivered(
                        task_id, table=table, deliver_error=text_err
                    )
                except Exception as exc:
                    _log.exception(
                        "mark after file_sent failed task_id=%s", task_id
                    )
                    _set_deliver_error(task_id, str(exc), table=table)
                    return False
                self._audit(
                    done,
                    chat_id=chat_id,
                    channel="file+reply",
                    outcome=(
                        "file_ok_text_failed" if text_err else "ok_mark_retry"
                    ),
                    error=text_err,
                )
                self._forget_file_sent(task_id)
                return True

            if not zip_path.is_file():
                if _age_since_finish_sec(done) < config.ZIP_WAIT_SEC:
                    return False
                if task_id not in self._zip_timeout_warned:
                    self._zip_timeout_warned.add(task_id)
                    try:
                        self._channel.reply_text(
                            chat_id,
                            _user_task_card(
                                "处理已完成，但结果包未能生成，已停止回传",
                                label=label,
                                task_id=task_id,
                            ),
                            at_user_ids=at_ids,
                        )
                    except Exception as exc:
                        _log.exception(
                            "deliver zip-timeout notice failed task_id=%s",
                            task_id,
                        )
                        self._audit(
                            done,
                            chat_id=chat_id,
                            channel="reply",
                            outcome="zip_missing_notice_failed",
                            error=str(exc),
                        )
                    self._audit(
                        done,
                        chat_id=chat_id,
                        channel="reply",
                        outcome="zip_missing_abandoned",
                    )
                return self._abandon_delivery(
                    done,
                    chat_id=chat_id,
                    reason="buf_done zip missing after wait",
                    notify=False,
                )

            try:
                self._channel.send_file(chat_id, zip_path)
                self._remember_file_sent(task_id)
            except Exception as exc:
                _log.exception("deliver file failed task_id=%s", task_id)
                err = _clip_err(str(exc))
                _set_deliver_error(task_id, err, table=table)
                self._audit(
                    done,
                    chat_id=chat_id,
                    channel="file",
                    outcome="file_failed",
                    error=err,
                )
                if task_id not in self._deliver_fail_warned:
                    self._deliver_fail_warned.add(task_id)
                    try:
                        self._channel.reply_text(
                            chat_id,
                            _user_task_card(
                                "结果发送失败，将自动重试",
                                label=label,
                                task_id=task_id,
                            ),
                            at_user_ids=at_ids,
                        )
                    except Exception:
                        _log.exception(
                            "deliver failure notice failed task_id=%s", task_id
                        )
                if _non_retryable_deliver_error(exc):
                    return self._abandon_delivery(
                        done,
                        chat_id=chat_id,
                        reason=err,
                        notify=False,
                    )
                attempts = self._bump_attempt(task_id)
                if attempts >= max_attempts:
                    return self._abandon_delivery(
                        done,
                        chat_id=chat_id,
                        reason=f"file send failed x{attempts}: {err}",
                        notify=False,
                    )
                return False

            text_err = ""
            try:
                self._channel.reply_text(
                    chat_id,
                    _user_task_card(
                        "处理完成，结果已发到本群",
                        label=label,
                        task_id=task_id,
                        extra=[
                            f"文件：{zip_path.name}",
                            "解压密码可用 query password 查询。",
                        ],
                    ),
                    at_user_ids=at_ids,
                )
            except Exception as exc:
                text_err = _clip_err(str(exc))
                _log.exception(
                    "deliver text failed after file ok task_id=%s", task_id
                )

            try:
                _mark_delivered(
                    task_id, table=table, deliver_error=text_err
                )
            except Exception as exc:
                # File already sent — do not resend; retry mark next tick.
                _log.exception(
                    "mark_delivered failed after file ok task_id=%s", task_id
                )
                _set_deliver_error(task_id, str(exc), table=table)
                self._audit(
                    done,
                    chat_id=chat_id,
                    channel="file+reply",
                    outcome="file_ok_mark_failed",
                    error=str(exc),
                )
                return False

            self._audit(
                done,
                chat_id=chat_id,
                channel="file+reply",
                outcome="file_ok_text_failed" if text_err else "ok",
                error=text_err,
            )
            self._forget_file_sent(task_id)
            return True

        err = done.get("error") or st
        try:
            self._channel.reply_text(
                chat_id,
                _user_task_card(
                    "未能完成",
                    label=label,
                    task_id=task_id,
                    extra=[
                        f"状态：{st}",
                        f"原因：{_clip_err(str(err))}",
                    ],
                ),
                at_user_ids=at_ids,
            )
        except Exception as exc:
            _log.exception("deliver terminal text failed task_id=%s", task_id)
            self._audit(
                done,
                chat_id=chat_id,
                channel="reply",
                outcome="terminal_text_failed",
                error=str(exc),
            )
            _set_deliver_error(task_id, str(exc), table=table)
            if _non_retryable_deliver_error(exc):
                return self._abandon_delivery(
                    done,
                    chat_id=chat_id,
                    reason=_clip_err(str(exc)),
                    notify=False,
                )
            attempts = self._bump_attempt(task_id)
            if attempts >= max_attempts:
                return self._abandon_delivery(
                    done,
                    chat_id=chat_id,
                    reason=f"terminal text failed x{attempts}",
                    notify=False,
                )
            return False
        try:
            _mark_delivered(task_id, table=table, deliver_error="")
        except Exception as exc:
            _log.exception("mark terminal delivered failed task_id=%s", task_id)
            _set_deliver_error(task_id, str(exc), table=table)
            return False
        self._audit(
            done,
            chat_id=chat_id,
            channel="reply",
            outcome="ok",
        )
        return True


def _resolve_delivery_chat(done: dict) -> str:
    """Task results only go to the recorded chat — never announce fallback."""
    return str(done.get("im_chat_id") or "").strip()


def _processed_dir() -> Path:
    if not config.MODULES:
        return Path(config.INBOX_DIR).parent / "state" / "processed"
    return Path(config.MODULES[0].state_dir) / "processed"


def _source_accepted(source_file: str) -> bool:
    """True if Module A ledger already has a row for this inbox filename."""
    name = (source_file or "").strip()
    if not name:
        return False
    db = Path(config.TASKS_DB)
    if not db.is_file():
        return False
    uri = f"file:{db.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    try:
        for spec in config.MODULES:
            try:
                row = conn.execute(
                    f"SELECT 1 FROM {spec.tasks_table} WHERE source_file=? LIMIT 1",
                    (name,),
                ).fetchone()
            except sqlite3.OperationalError:
                continue
            if row is not None:
                return True
        return False
    finally:
        conn.close()


def _urls_already_active(urls: list[str]) -> bool:
    cleaned = [(u or "").strip() for u in urls if (u or "").strip()]
    if not cleaned:
        return False
    db = Path(config.TASKS_DB)
    if not db.is_file():
        return False
    uri = f"file:{db.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    try:
        for url in cleaned:
            found = False
            for spec in config.MODULES:
                active = tuple(sorted(spec.active_statuses))
                if not active:
                    continue
                placeholders = ",".join("?" * len(active))
                try:
                    row = conn.execute(
                        f"SELECT 1 FROM {spec.tasks_table} "
                        f"WHERE url=? AND status IN ({placeholders}) LIMIT 1",
                        (url, *active),
                    ).fetchone()
                except sqlite3.OperationalError:
                    continue
                if row is not None:
                    found = True
                    break
            if not found:
                return False
        return True
    finally:
        conn.close()


def _source_processed_ok(source_file: str) -> bool:
    name = (source_file or "").strip()
    if not name:
        return False
    return (_processed_dir() / name).is_file()


def _source_rejected(source_file: str) -> bool:
    name = (source_file or "").strip()
    if not name:
        return False
    return (_processed_dir() / f"rejected_{name}").is_file()


def _inbox_file_stale(path: Path) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return True
    return age >= float(config.PENDING_INBOX_STALE_TOUCH_SEC)


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


def _set_deliver_error(
    task_id: str, error: str, *, table: str | None = None
) -> None:
    db = Path(config.TASKS_DB)
    if not db.is_file():
        return
    tbl = table or config.TASKS_TABLE
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    err = _clip_err(error)
    conn = sqlite3.connect(str(db), timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                f"UPDATE {tbl} SET im_deliver_error=?, updated_at=? WHERE task_id=?",
                (err, now, task_id),
            )
        except sqlite3.OperationalError:
            # Column may be missing on very old DBs until Module A migrates.
            pass
        conn.commit()
    except Exception:
        conn.rollback()
        _log.exception("set im_deliver_error failed task_id=%s", task_id)
    finally:
        conn.close()


def _mark_delivered(
    task_id: str,
    *,
    table: str | None = None,
    deliver_error: str = "",
) -> None:
    db = Path(config.TASKS_DB)
    if not db.is_file():
        return
    tbl = table or config.TASKS_TABLE
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    err = _clip_err(deliver_error) if deliver_error else ""
    conn = sqlite3.connect(str(db), timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                f"UPDATE {tbl} SET im_delivered_at=?, im_deliver_error=?, "
                "updated_at=? WHERE task_id=?",
                (now, err, now, task_id),
            )
        except sqlite3.OperationalError:
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
