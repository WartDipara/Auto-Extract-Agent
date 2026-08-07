"""OpenCode stream event completeness + idle/wrap-up helpers."""

from __future__ import annotations

import json
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


def test_stream_event_state_incomplete_tool():
    import opencode_session as oc

    st = oc._StreamEventState()
    st.observe("tool_use", "bash")
    assert st.incomplete
    assert st.open_tool == "bash"
    st.observe("tool_result", "bash")
    assert not st.incomplete


def test_stream_event_state_step_pair():
    import opencode_session as oc

    st = oc._StreamEventState()
    st.observe("step_start")
    st.observe("tool_use", "write")
    assert st.incomplete
    st.observe("tool_result", "write")
    st.observe("step_finish")
    assert not st.incomplete


def test_parse_json_event_tool_types():
    import opencode_session as oc

    line = json.dumps(
        {"type": "tool_use", "sessionID": "ses_x", "part": {"name": "bash"}}
    )
    sid, human, etype, tool = oc._parse_json_event(line)
    assert sid == "ses_x"
    assert etype == "tool_use"
    assert tool == "bash"
    assert "bash" in human


def test_abnormal_stop_on_incomplete_exit(tmp_path, monkeypatch):
    import config
    import opencode_session as oc

    monkeypatch.setattr(config, "OPENCODE_IDLE_HEARTBEAT_SEC", 30)
    # Emit a tool_use then exit — no tool_result.
    payload = json.dumps(
        {"type": "tool_use", "sessionID": "ses_abn", "part": {"name": "bash"}}
    )
    cmd = [
        sys.executable,
        "-u",
        "-c",
        f"print({payload!r}, flush=True)",
    ]
    result = oc._run_json_stream(
        cmd,
        cwd=tmp_path,
        print_live=True,
        stall_sec=None,
        hard_timeout_sec=30,
        idle_sec=30,
        stop_path=None,
    )
    assert result.kill_reason == "abnormal_stop"
    assert result.stalled is True
    assert result.open_tool == "bash"
    assert result.session_id == "ses_abn"


def test_wrapup_hard_timeout_cuts_fast(tmp_path, monkeypatch):
    import config
    import opencode_session as oc

    monkeypatch.setattr(config, "OPENCODE_IDLE_HEARTBEAT_SEC", 1)
    cmd = [
        sys.executable,
        "-u",
        "-c",
        "import time; print('hi', flush=True); time.sleep(120)",
    ]
    t0 = time.monotonic()
    result = oc._run_json_stream(
        cmd,
        cwd=tmp_path,
        print_live=True,
        stall_sec=None,
        hard_timeout_sec=3,
        idle_sec=60,
        stop_path=None,
    )
    elapsed = time.monotonic() - t0
    assert result.kill_reason == "hard_timeout"
    assert result.stalled is True
    assert elapsed < 20
