"""
OpenCode 对话/会话管理：一任务一会话，新任务新开会话，session 落盘到 state。
state 只记录 task_key + session_id + exit_code。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import config

_log = logging.getLogger(__name__)

_active_lock = threading.Lock()
_active_proc: subprocess.Popen | None = None
_active_stop_path: Path | None = None


@dataclass
class OpenCodeRunResult:
    returncode: int
    session_id: str = ""
    stdout_text: str = ""
    stalled: bool = False
    # None | "stall" | "hard_timeout" | "stop" | "interrupt"
    kill_reason: str | None = None


@dataclass
class SessionRecord:
    task_key: str
    session_id: str
    exit_code: int | None = None


class OpenCodeStopped(RuntimeError):
    """OpenCode was stopped via .stop marker or interrupt."""


def output_csv_has_content(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    except OSError:
        return False
    return bool(text)


def export_session_json(
    session_id: str,
    *,
    cwd: Path,
    out_path: Path,
) -> Path:
    """Run `opencode export <sessionID>` and write pretty JSON to out_path."""
    sid = (session_id or "").strip()
    if not sid:
        raise ValueError("session_id is empty")
    opencode = shutil.which(config.OPENCODE_CMD) or config.OPENCODE_CMD
    cmd = [opencode, "export", sid]
    _log.info("opencode export session=%s -> %s", sid, out_path)
    print(f"opencode export session={sid}", flush=True)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"opencode export failed exit={proc.returncode}: {detail}")
    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError("opencode export produced empty stdout")
    data = json.loads(raw)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"opencode export wrote {out} ({out.stat().st_size} bytes)", flush=True)
    return out


def interrupt_active_run() -> bool:
    """
    Mark .stop (if known) and kill the active OpenCode process tree.
    Safe to call from SIGINT / main shutdown. Returns True if a proc was targeted.
    """
    with _active_lock:
        proc = _active_proc
        stop_path = _active_stop_path
    if stop_path is not None:
        try:
            stop_path.parent.mkdir(parents=True, exist_ok=True)
            stop_path.write_text("", encoding="utf-8")
            _log.info("wrote stop marker: %s", stop_path)
            print(f"stop marker written: {stop_path}", flush=True)
        except OSError as exc:
            _log.warning("cannot write stop marker %s: %s", stop_path, exc)
    if proc is None or proc.poll() is not None:
        return False
    _log.info("interrupting opencode pid=%s", proc.pid)
    print(f"interrupting opencode pid={proc.pid}", flush=True)
    _kill_proc(proc)
    return True


def active_opencode_pid() -> int | None:
    """PID of the in-flight OpenCode process, or None."""
    with _active_lock:
        proc = _active_proc
    if proc is None or proc.poll() is not None:
        return None
    return proc.pid


def _set_active(proc: subprocess.Popen, stop_path: Path | None) -> None:
    global _active_proc, _active_stop_path
    with _active_lock:
        _active_proc = proc
        _active_stop_path = stop_path


def _clear_active(proc: subprocess.Popen) -> None:
    global _active_proc, _active_stop_path
    with _active_lock:
        if _active_proc is proc:
            _active_proc = None
            _active_stop_path = None


class OpenCodeSessionManager:
    """
    - 无 session 则新开；已有则 --session 续聊（不 --fork）
    - 每次 run 用 --format json 解析 sessionID，写入 state/opencode_sessions.jsonl
    - 落盘字段：task_key, session_id, exit_code
    """

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or config.OPENCODE_SESSIONS_FILE
        self._by_task: dict[str, SessionRecord] = {}
        self._load()

    def _load(self):
        self._by_task.clear()
        if not self.state_path.is_file():
            return
        try:
            text = self.state_path.read_text(encoding="utf-8")
        except OSError as exc:
            _log.warning("cannot read %s: %s", self.state_path, exc)
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = data.get("task_key") or ""
            sid = data.get("session_id") or ""
            if not key or not sid:
                continue
            exit_code = data.get("exit_code", None)
            if exit_code is not None:
                try:
                    exit_code = int(exit_code)
                except (TypeError, ValueError):
                    exit_code = None
            self._by_task[key] = SessionRecord(
                task_key=key, session_id=sid, exit_code=exit_code
            )

    def get(self, task_key: str) -> SessionRecord | None:
        return self._by_task.get(task_key)

    def lookup_session_id(self, task_key: str) -> str:
        rec = self._by_task.get(task_key)
        return rec.session_id if rec else ""

    def _append_record(self, rec: SessionRecord):
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "task_key": rec.task_key,
            "session_id": rec.session_id,
            "exit_code": rec.exit_code,
        }
        with self.state_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._by_task[rec.task_key] = rec
        _log.info(
            "opencode session recorded task=%s session=%s exit_code=%s",
            rec.task_key,
            rec.session_id,
            rec.exit_code,
        )

    def bind_session(
        self,
        task_key: str,
        session_id: str,
        *,
        exit_code: int | None = None,
    ) -> SessionRecord:
        rec = SessionRecord(
            task_key=task_key, session_id=session_id, exit_code=exit_code
        )
        self._append_record(rec)
        return rec

    def run(
        self,
        *,
        task_key: str,
        prompt: str,
        cwd: Path,
        skill: str | None = None,
        variant: str | None = None,
        auto: bool = True,
        force_new: bool = False,
        print_live: bool = True,
        stall_sec: float | None = None,
        stall_output_path: Path | None = None,
        hard_timeout_sec: float | None = None,
        stop_path: Path | None = None,
    ) -> OpenCodeRunResult:
        """
        若该 task_key 尚无 session（或 force_new），开新会话；
        否则用 --session <session_id> 续聊，保证同一任务不新开窗口。
        skill 仅作本次 CLI --command，不写入 state。

        stall_sec: 若进程仍在跑且 stall_output_path 仍无有效内容，超时则 kill，
        返回 stalled=True（用于 resume.stall_continue / deadline_persist）。
        若期间已写出有效产物，则不再因 stall 杀进程，改等自然退出或 hard_timeout。

        stop_path: 若该文件出现，杀进程树并以 kill_reason="stop" 返回。
        """
        if stop_path is not None and stop_path.is_file():
            _log.info("stop marker present before run: %s", stop_path)
            return OpenCodeRunResult(returncode=-1, kill_reason="stop", stalled=True)

        opencode = shutil.which(config.OPENCODE_CMD) or config.OPENCODE_CMD
        existing = None if force_new else self._by_task.get(task_key)
        session_id = existing.session_id if existing else ""

        cmd = [opencode, "run", "--format", "json"]
        if auto:
            cmd.append("--auto")
        v = variant if variant is not None else config.OPENCODE_VARIANT
        if v:
            cmd.extend(["--variant", v])
        cmd.extend(["--dir", str(cwd)])

        if session_id:
            cmd.extend(["--session", session_id])
            label = f"opencode resume task={task_key} session={session_id}"
        else:
            cmd.extend(["--title", task_key])
            if skill:
                cmd.extend(["--command", skill])
            label = f"opencode new task={task_key}"

        cmd.append(prompt)
        _log.info("%s", label)
        print(f"=== {label} ===", flush=True)

        result = _run_json_stream(
            cmd,
            cwd=cwd,
            print_live=print_live,
            stall_sec=stall_sec,
            stall_output_path=stall_output_path,
            hard_timeout_sec=hard_timeout_sec,
            stop_path=stop_path,
        )
        sid = result.session_id or session_id
        if sid:
            self.bind_session(task_key, sid, exit_code=result.returncode)
            result.session_id = sid
        return result


def _popen_kwargs() -> dict:
    kwargs: dict = {}
    if os.name == "nt":
        # Separate group so Ctrl+C on the console does not instantly tear
        # the child before we can write .stop and kill the tree ourselves.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _run_json_stream(
    cmd: list[str],
    *,
    cwd: Path,
    print_live: bool,
    stall_sec: float | None = None,
    stall_output_path: Path | None = None,
    hard_timeout_sec: float | None = None,
    stop_path: Path | None = None,
) -> OpenCodeRunResult:
    import queue as queue_mod

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        **_popen_kwargs(),
    )
    assert proc.stdout is not None
    _set_active(proc, stop_path)
    session_id = ""
    text_chunks: list[str] = []
    stalled = False
    kill_reason: str | None = None
    print("--- live output ---", flush=True)

    line_queue: queue_mod.Queue = queue_mod.Queue()

    def _reader():
        try:
            while True:
                raw = proc.stdout.readline()
                if raw == b"":
                    break
                line_queue.put(_decode(raw).rstrip("\r\n"))
        finally:
            line_queue.put(None)

    threading.Thread(target=_reader, name="opencode-stdout", daemon=True).start()

    start = time.monotonic()
    stall_deadline = (start + stall_sec) if stall_sec and stall_sec > 0 else None
    hard_deadline = (
        (start + hard_timeout_sec)
        if hard_timeout_sec and hard_timeout_sec > 0
        else None
    )
    stall_armed = stall_deadline is not None

    try:
        while True:
            now = time.monotonic()
            if stop_path is not None and stop_path.is_file():
                _log.info("opencode stop marker detected: %s", stop_path)
                print(f"stop marker detected; killing opencode pid={proc.pid}", flush=True)
                stalled = True
                kill_reason = "stop"
                _kill_proc(proc)
                break

            if hard_deadline is not None and now >= hard_deadline:
                _log.error("opencode hard timeout after %ss", hard_timeout_sec)
                stalled = True
                kill_reason = "hard_timeout"
                _kill_proc(proc)
                break

            if stall_armed and stall_deadline is not None and now >= stall_deadline:
                if output_csv_has_content(stall_output_path):
                    stall_armed = False
                    _log.info("stall reached but output exists; wait for process exit")
                    print(
                        "stall reached but tests.csv exists; waiting exit...",
                        flush=True,
                    )
                else:
                    _log.warning(
                        "opencode stall after %ss (no output at %s)",
                        stall_sec,
                        stall_output_path,
                    )
                    print(
                        f"stall after {int(stall_sec)}s (no valid output); killing...",
                        flush=True,
                    )
                    stalled = True
                    kill_reason = "stall"
                    _kill_proc(proc)
                    break

            try:
                line = line_queue.get(timeout=0.2)
            except queue_mod.Empty:
                if proc.poll() is not None and line_queue.empty():
                    if (
                        kill_reason is None
                        and stop_path is not None
                        and stop_path.is_file()
                    ):
                        kill_reason = "stop"
                        stalled = True
                    break
                continue
            if line is None:
                if (
                    kill_reason is None
                    and stop_path is not None
                    and stop_path.is_file()
                ):
                    kill_reason = "stop"
                    stalled = True
                break
            if not line:
                continue
            sid, human = _parse_json_event(line)
            if sid and not session_id:
                session_id = sid
            if human:
                text_chunks.append(human)
                if print_live:
                    print(human, end="" if human.endswith("\n") else "\n", flush=True)
            elif print_live and not line.startswith("{"):
                print(line, flush=True)
    except KeyboardInterrupt:
        _log.warning("KeyboardInterrupt during opencode; killing process tree")
        print("KeyboardInterrupt; killing opencode process tree...", flush=True)
        if stop_path is not None:
            try:
                stop_path.parent.mkdir(parents=True, exist_ok=True)
                stop_path.write_text("", encoding="utf-8")
            except OSError:
                pass
        stalled = True
        kill_reason = "interrupt"
        _kill_proc(proc)
    finally:
        _clear_active(proc)

    # drain after kill / EOF
    while True:
        try:
            line = line_queue.get_nowait()
        except queue_mod.Empty:
            break
        if line is None:
            break
        if not line:
            continue
        sid, human = _parse_json_event(line)
        if sid and not session_id:
            session_id = sid
        if human:
            text_chunks.append(human)
            if print_live:
                print(human, end="" if human.endswith("\n") else "\n", flush=True)

    code = proc.wait()
    print(
        f"--- end exit_code={code} session={session_id or '-'} "
        f"stalled={stalled} kill_reason={kill_reason or '-'} ---",
        flush=True,
    )
    return OpenCodeRunResult(
        returncode=code,
        session_id=session_id,
        stdout_text="".join(text_chunks),
        stalled=stalled,
        kill_reason=kill_reason,
    )


def _kill_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    pid = proc.pid
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_json_event(line: str) -> tuple[str, str]:
    """Return (session_id, human_text). human_text may be empty."""
    if not line.startswith("{"):
        return "", ""
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return "", ""
    sid = str(ev.get("sessionID") or "")
    etype = ev.get("type") or ""
    part = ev.get("part") or {}
    if isinstance(part, dict):
        sid = sid or str(part.get("sessionID") or "")
    human = ""
    if etype == "text":
        human = str((part or {}).get("text") or "")
    elif etype in ("tool_use", "tool_call"):
        name = (part or {}).get("name") or (part or {}).get("tool") or "tool"
        human = f"→ {name}\n"
    return sid, human
