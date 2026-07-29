"""Thin OpenCode resume wrapper (no auto-extract imports)."""

from __future__ import annotations

import logging
import os
import queue as queue_mod
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)


@dataclass
class ResumeResult:
    returncode: int
    session_id: str = ""
    stdout_text: str = ""


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_json_event(line: str) -> tuple[str, str]:
    import json

    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return "", ""
    if not isinstance(ev, dict):
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


def resume_opencode(
    *,
    session_id: str,
    prompt: str,
    cwd: Path,
    print_live: bool = True,
) -> ResumeResult:
    opencode = os.environ.get("OPENCODE_CMD", "opencode").strip() or "opencode"
    opencode = shutil.which(opencode) or opencode
    variant = os.environ.get("OPENCODE_VARIANT", "max").strip() or "max"

    cmd = [
        opencode,
        "run",
        "--format",
        "json",
        "--auto",
        "--variant",
        variant,
        "--dir",
        str(Path(cwd).resolve()),
        "--session",
        session_id,
        prompt,
    ]
    label = f"opencode resume session={session_id}"
    _log.info("%s", label)
    print(f"=== {label} ===", flush=True)
    print("--- live output ---", flush=True)

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    assert proc.stdout is not None
    line_queue: queue_mod.Queue = queue_mod.Queue()
    chunks: list[str] = []
    seen_sid = session_id

    def _reader():
        try:
            while True:
                raw = proc.stdout.readline()
                if raw == b"":
                    break
                line_queue.put(_decode(raw).rstrip("\r\n"))
        finally:
            line_queue.put(None)

    threading.Thread(target=_reader, name="opencode-resume-stdout", daemon=True).start()

    while True:
        try:
            line = line_queue.get(timeout=0.2)
        except queue_mod.Empty:
            if proc.poll() is not None and line_queue.empty():
                break
            continue
        if line is None:
            break
        if not line:
            continue
        sid, human = _parse_json_event(line)
        if sid:
            seen_sid = sid
        if human:
            chunks.append(human)
            if print_live:
                print(human, end="" if human.endswith("\n") else "\n", flush=True)
        elif print_live and not line.startswith("{"):
            print(line, flush=True)

    code = proc.wait()
    print(
        f"--- end exit_code={code} session={seen_sid or '-'} ---",
        flush=True,
    )
    return ResumeResult(
        returncode=code,
        session_id=seen_sid,
        stdout_text="".join(chunks),
    )
