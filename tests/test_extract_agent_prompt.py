"""
OpenCode prompt smoke test for apps/auto-extract.

  cd D:\\smwl\\Auto-Extract-Agent
  $env:PYTHONUTF8 = "1"
  python .\\tests\\test_extract_agent_prompt.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_APP = _REPO / "apps" / "auto-extract"
_SRC = _APP / "src"
for p in (_SRC, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def test_opencode_prompt_and_cmd():
    import config
    import extract_bridge as eb
    from shared.archive_contract import reset_task_workspace, task_layout

    task_root = reset_task_workspace(config.WORKSPACE_ROOT, "_smoke_prompt")
    eb._task_root = task_root
    layout = task_layout(task_root)
    snap = {
        "root": str(layout["root"].resolve()),
        "decoded_dir": str(layout["decoded"].resolve()),
        "hotfix_dir": str(layout["hotfix"].resolve()),
        "outputs_dir": str(layout["outputs"].resolve()),
        "decoded_files": 10,
        "hotfix_files": 0,
    }
    apk_name = "demo.apk"
    prompt = eb.build_opencode_prompt(apk_name, snap)
    cmd = eb.build_opencode_cmd(prompt)

    assert "禁止询问用户" in prompt
    assert "hotfix" in prompt
    assert "apks=" not in prompt
    assert config.OPENCODE_OUTPUT_NAME in prompt or "tests.csv" in prompt
    assert config.OPENCODE_SKILL in prompt
    assert config.OPENCODE_SKILL in cmd
    assert "--auto" in cmd
    assert eb.opencode_output_csv().name == "tests.csv"
    assert layout["opencode_export"].name == "opencode_session.json"
    assert eb.build_opencode_resume_prompt("stall_continue", apk_name, snap).strip() == "继续"
    too_few = eb.build_opencode_resume_prompt(
        "quality_too_few",
        apk_name,
        snap,
        line_count=100,
        min_lines=config.CSV_MIN_LINES,
        garbled_lines=0,
    )
    garbled = eb.build_opencode_resume_prompt(
        "quality_garbled",
        apk_name,
        snap,
        line_count=100,
        min_lines=config.CSV_MIN_LINES,
        garbled_lines=20,
    )
    assert "提取不完整" in too_few or "太少" in too_few or "下限" in too_few
    assert str(config.CSV_MIN_LINES) in too_few
    assert "乱码" in garbled
    assert "解密" in garbled
    print("prompt chars:", len(prompt), flush=True)
    print("EXTRACT_AGENT_PROMPT_OK", flush=True)


def test_csv_quality():
    import config
    from csv_quality import check_csv_quality, line_looks_garbled
    from shared.sensitive_words import filter_sensitive_lines

    assert line_looks_garbled("bad\ufffdtext")
    assert line_looks_garbled("Ã¤Â¸Â­Ã¦Â–Â‡xx")
    assert not line_looks_garbled("这是正常中文文本")

    few = "\n".join(f"行{i}" for i in range(10))
    issue = check_csv_quality(few)
    assert issue is not None and issue.kind == "too_few"

    good_lines = [f"任务奖励说明{i}" for i in range(config.CSV_MIN_LINES)]
    assert check_csv_quality("\n".join(good_lines)) is None

    garbled_body = "\n".join(
        ["Ã¤Â¸Â­Ã¦Â–Â‡乱码样例"] * (config.CSV_GARBLE_MIN_LINES + 1)
        + good_lines
    )
    issue2 = check_csv_quality(garbled_body)
    assert issue2 is not None and issue2.kind == "garbled"

    assert check_csv_quality(config.DECRYPT_FAIL_TEXT) is None

    words = frozenset({"色情论坛", "一夜性网", "习"})
    raw = "任务说明\n色情论坛\n正常文本\n一夜性网\n习\n包含色情论坛的长句\n"
    filtered, removed = filter_sensitive_lines(raw, words=words)
    assert removed == 3
    assert filtered.splitlines() == ["任务说明", "正常文本", "包含色情论坛的长句"]
    assert check_csv_quality(filtered) is not None
    print("CSV_QUALITY_OK", flush=True)


def test_workspace_markers():
    import config
    from shared.archive_contract import (
        FollowupLockedError,
        acquire_followup_lock,
        has_module_a_done,
        mark_module_a_done,
        release_followup_lock,
        reset_task_workspace,
        rmtree_force,
    )

    key = "_smoke_markers"
    root = reset_task_workspace(config.WORKSPACE_ROOT, key)
    assert not has_module_a_done(root)
    try:
        acquire_followup_lock(root)
        assert False, "expected RuntimeError without a_done"
    except RuntimeError:
        pass
    mark_module_a_done(root)
    assert has_module_a_done(root)
    acquire_followup_lock(root)
    try:
        reset_task_workspace(config.WORKSPACE_ROOT, key)
        assert False, "expected FollowupLockedError"
    except FollowupLockedError:
        pass
    release_followup_lock(root)

    from shared.archive_contract import has_stop, mark_stop

    mark_stop(root)
    assert has_stop(root)
    try:
        acquire_followup_lock(root)
        assert False, "expected RuntimeError when stopped"
    except RuntimeError:
        pass

    root2 = reset_task_workspace(config.WORKSPACE_ROOT, key)
    assert root2 == root
    assert not has_module_a_done(root2)
    rmtree_force(root2)
    print("WORKSPACE_MARKERS_OK", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    test_opencode_prompt_and_cmd()
    test_csv_quality()
    test_workspace_markers()
