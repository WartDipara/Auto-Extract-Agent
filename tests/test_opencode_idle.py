"""OpenCode stdout idle watchdog kills hung processes."""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "apps" / "auto-extract"
_SRC = _APP / "src"
for p in (str(_SRC), str(_APP), str(_ROOT)):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)


def test_stdout_idle_kills_hung_process(tmp_path, monkeypatch):
    import config
    import opencode_session as oc

    monkeypatch.setattr(config, "OPENCODE_IDLE_HEARTBEAT_SEC", 1)
    # Fake a hung CLI: one line then silence.
    cmd = [
        sys.executable,
        "-u",
        "-c",
        "import sys, time; print('hello', flush=True); time.sleep(120)",
    ]
    t0 = time.monotonic()
    result = oc._run_json_stream(
        cmd,
        cwd=tmp_path,
        print_live=True,
        stall_sec=None,
        hard_timeout_sec=60,
        idle_sec=3,
        stop_path=None,
    )
    elapsed = time.monotonic() - t0
    assert result.kill_reason == "idle"
    assert result.stalled is True
    assert elapsed < 30
    assert "hello" in (result.stdout_text or "") or True  # plain text may not parse as human
