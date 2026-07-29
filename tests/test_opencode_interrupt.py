"""
OpenCode interrupt smoke test: start a long run, write .stop, assert clean kill.

  cd D:\\smwl\\Auto-Extract-Agent
  $env:PYTHONUTF8 = "1"
  python .\\tests\\test_opencode_interrupt.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_APP = _REPO / "apps" / "auto-extract"
_SRC = _APP / "src"
for p in (_SRC, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from opencode_session import OpenCodeSessionManager, active_opencode_pid  # noqa: E402
from shared.archive_contract import (  # noqa: E402
    mark_stop,
    purge_stopped_workspaces,
    task_layout,
)

_TASK_KEY = f"interrupt-stop-{int(time.time())}"
_CWD = _HERE / "interrupt_workspace" / _TASK_KEY
_PROMPT = (
    "这是打断冒烟测试。请从 1 慢慢数到 100000，每行只输出一个数字。"
    "不要调用任何工具，不要改文件，不要提前结束。"
)
_STOP_AFTER_SEC = 8.0


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        out = (proc.stdout or "").strip()
        return str(pid) in out and "No tasks" not in out and "没有" not in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_opencode_stop_marker_kills_process():
    layout = task_layout(_CWD)
    for key in ("decoded", "hotfix", "outputs"):
        layout[key].mkdir(parents=True, exist_ok=True)

    mgr = OpenCodeSessionManager()
    stop_path = layout["stop"]
    result_box: dict = {}

    def _runner():
        result_box["result"] = mgr.run(
            task_key=_TASK_KEY,
            prompt=_PROMPT,
            cwd=_CWD,
            skill=None,
            auto=True,
            force_new=True,
            print_live=True,
            stop_path=stop_path,
            hard_timeout_sec=120,
        )

    print("=== OPENCODE INTERRUPT RUN ===", flush=True)
    print(f"workspace={_CWD}", flush=True)
    print(f"stop_path={stop_path}", flush=True)
    thread = threading.Thread(target=_runner, name="opencode-interrupt", daemon=True)
    thread.start()

    # Wait until OpenCode is registered as active, then mark .stop.
    deadline = time.monotonic() + 60
    pid = None
    while time.monotonic() < deadline:
        pid = active_opencode_pid()
        if pid is not None:
            break
        time.sleep(0.2)
    if pid is None:
        raise AssertionError("opencode process did not start within 60s")

    print(f"opencode pid={pid}; waiting {_STOP_AFTER_SEC}s then writing .stop", flush=True)
    time.sleep(_STOP_AFTER_SEC)
    mark_stop(_CWD)
    print(f"wrote stop marker: {stop_path}", flush=True)

    thread.join(timeout=60)
    if thread.is_alive():
        raise AssertionError("opencode run did not exit within 60s after .stop")

    result = result_box.get("result")
    if result is None:
        raise AssertionError("missing run result")
    print(
        f"run exit={result.returncode} session={result.session_id or '-'} "
        f"kill_reason={result.kill_reason}",
        flush=True,
    )
    if result.kill_reason != "stop":
        raise AssertionError(f"expected kill_reason=stop, got {result.kill_reason!r}")

    # Give Windows a moment to reap the tree.
    time.sleep(1.0)
    if _pid_alive(pid):
        raise AssertionError(f"opencode pid {pid} still alive after stop")

    deleted = purge_stopped_workspaces(_CWD.parent)
    print(f"purge deleted={deleted}", flush=True)
    if _TASK_KEY not in deleted:
        raise AssertionError(f"expected purge to delete {_TASK_KEY}, got {deleted}")
    if _CWD.exists():
        raise AssertionError(f"workspace still exists after purge: {_CWD}")

    print("OPENCODE_INTERRUPT_OK", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    test_opencode_stop_marker_kills_process()
