"""Lightweight OpenCode liveness probe (no skill, no long thinking)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

_PING_PROMPT = (
    "Reply with exactly one word and nothing else: pong"
)
_DEFAULT_TIMEOUT_SEC = 90.0


@dataclass(frozen=True)
class OpenCodePingResult:
    ok: bool
    message: str
    raw_text: str = ""


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_text_event(line: str) -> str:
    if not line.startswith("{"):
        return ""
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return ""
    if (ev.get("type") or "") != "text":
        return ""
    part = ev.get("part") or {}
    if not isinstance(part, dict):
        return ""
    return str(part.get("text") or "")


def _looks_like_pong(text: str) -> bool:
    blob = " ".join((text or "").lower().split())
    if not blob:
        return False
    if blob == "pong":
        return True
    # Allow tiny wrappers: "pong." / "pong!"
    return blob.strip(".!！。") == "pong" or "pong" in blob.split()


def ping_opencode(
    *,
    cmd: str | None = None,
    cwd: Path | None = None,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
) -> OpenCodePingResult:
    """
    Run a one-shot `opencode run` and require a short 'pong' reply.
    Does not attach extract skills or resume long sessions.
    """
    exe = shutil.which((cmd or os.environ.get("OPENCODE_CMD") or "opencode").strip()) or (
        cmd or "opencode"
    )
    work = Path(cwd) if cwd is not None else Path.cwd()
    work.mkdir(parents=True, exist_ok=True)
    argv = [
        exe,
        "run",
        "--format",
        "json",
        "--dir",
        str(work),
        "--title",
        "im-opencode-ping",
        _PING_PROMPT,
    ]
    _log.info("opencode ping cmd=%s cwd=%s timeout=%s", exe, work, timeout_sec)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(work),
            capture_output=True,
            timeout=max(5.0, float(timeout_sec)),
        )
    except FileNotFoundError:
        return OpenCodePingResult(ok=False, message=f"找不到命令: {exe}")
    except subprocess.TimeoutExpired:
        return OpenCodePingResult(
            ok=False, message=f"超时（>{int(timeout_sec)}s）无响应"
        )
    except Exception as exc:
        _log.exception("opencode ping failed")
        return OpenCodePingResult(ok=False, message=str(exc) or type(exc).__name__)

    chunks: list[str] = []
    for stream in (proc.stdout or b"", proc.stderr or b""):
        for line in _decode(stream).splitlines():
            human = _parse_text_event(line)
            if human:
                chunks.append(human)
            elif line and not line.startswith("{"):
                chunks.append(line)
    text = "".join(chunks).strip() or _decode(proc.stdout or b"").strip()
    if _looks_like_pong(text):
        return OpenCodePingResult(ok=True, message="pong", raw_text=text)
    if proc.returncode != 0:
        detail = text[:200] or f"exit={proc.returncode}"
        return OpenCodePingResult(
            ok=False, message=f"进程异常 exit={proc.returncode}: {detail}", raw_text=text
        )
    snippet = text[:120] if text else "(空回复)"
    return OpenCodePingResult(
        ok=False, message=f"未返回 pong：{snippet}", raw_text=text
    )
