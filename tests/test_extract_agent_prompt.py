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


def _ensure_auto_extract_imports() -> None:
    for p in (str(_APP), str(_SRC), str(_REPO)):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    cfg = sys.modules.get("config")
    if cfg is not None and not hasattr(cfg, "WORKSPACE_ROOT"):
        del sys.modules["config"]


def test_opencode_prompt_and_cmd():
    _ensure_auto_extract_imports()
    import config
    import extract_bridge as eb
    import prompts as prompt_store
    from apk_meta import resolve_source_lang
    from shared.archive_contract import reset_task_workspace, task_layout

    prompt_store.load_prompts(force_reload=True)

    assert resolve_source_lang({}) == "zh"
    assert resolve_source_lang(None) == "zh"
    assert resolve_source_lang({"zh-CN": "测试游戏"}) == "zh"
    assert (
        resolve_source_lang({"en": "Pack Leader: The Expedition"}) == "en"
    )
    assert (
        resolve_source_lang(
            {"zh-CN": "中文名", "en": "Pack Leader: The Expedition"}
        )
        == "zh"
    )

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
    stall = eb.build_opencode_resume_prompt("stall_continue", apk_name, snap)
    assert "半小时" in stall and "继续" in stall
    empty = eb.build_opencode_resume_prompt("classify_empty", apk_name, snap)
    assert config.ASSETS_MISSING_TEXT in empty
    assert config.DECRYPT_FAIL_TEXT in empty
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
    assert "技能" in too_few or "装备" in too_few or "对话" in too_few
    assert str(config.CSV_MIN_LINES) in too_few
    assert "乱码" in garbled
    assert "解密" in garbled
    review = eb.build_opencode_resume_prompt("final_csv_review", apk_name, snap)
    assert "乱码" in review
    assert "截断" in review
    assert "注释" in review or "调试" in review
    assert "错误提取" in review
    assert "富文本" in review or "color" in review
    large = eb.build_opencode_resume_prompt(
        "large_csv_review",
        apk_name,
        snap,
        line_count=350000,
        large_lines=config.CSV_LARGE_REVIEW_LINES,
    )
    assert "乱码" in large
    assert "违禁" in large or "敏感" in large
    assert "350000" in large
    assert str(config.CSV_LARGE_REVIEW_LINES) in large
    assert config.ASSETS_MISSING_TEXT in prompt
    assert "原语言=中文" in prompt
    assert "游戏原语言裁定" in prompt
    assert config.CSV_MIN_LINES == 5000
    sens = eb.build_opencode_resume_prompt(
        "quality_sensitive",
        apk_name,
        snap,
        hit_lines=6,
        samples="样例A；样例B",
    )
    assert "敏感" in sens
    assert "6" in sens

    zh_prompt = eb.build_opencode_prompt(
        apk_name,
        snap,
        labels={"zh-CN": "测试游戏", "en": "Test Game"},
        label="测试游戏",
    )
    assert "原语言=中文" in zh_prompt
    assert "测试游戏" in zh_prompt

    en_labels = {"en": "Pack Leader: The Expedition"}
    en_prompt = eb.build_opencode_prompt(
        apk_name,
        snap,
        labels=en_labels,
        label="Pack Leader: The Expedition",
    )
    assert "原语言=英文" in en_prompt
    assert "禁止再搜索" in en_prompt or "禁止再搜索/筛选中文" in en_prompt
    assert "Pack Leader: The Expedition" in en_prompt
    assert "原语言=中文" not in en_prompt

    en_resume = eb.build_opencode_resume_prompt(
        "final_csv_review",
        apk_name,
        snap,
        labels=en_labels,
        label="Pack Leader: The Expedition",
    )
    assert "原语言=英文" in en_resume

    assert eb.classify_csv(config.ASSETS_MISSING_TEXT) == "assets_missing"
    assert eb.classify_csv(config.DECRYPT_FAIL_TEXT + "（超时）") == "decrypt_failed"
    assert eb.classify_csv("text\n真实一行\n") == "success"
    print("prompt chars:", len(prompt), flush=True)
    print("EXTRACT_AGENT_PROMPT_OK", flush=True)


def test_csv_quality():
    _ensure_auto_extract_imports()
    import config
    from csv_quality import (
        check_csv_quality,
        has_extract_content,
        line_looks_garbled,
        match_terminal_status,
    )
    from shared.sensitive_words import filter_sensitive_lines, scan_sensitive_hits

    assert line_looks_garbled("bad\ufffdtext")
    assert line_looks_garbled("Ã¤Â¸Â­Ã¦Â–Â‡xx")
    assert line_looks_garbled("\x7f树精灵女皇？嫌疑犯的范围越缩越小了！")
    assert line_looks_garbled("装备\x7f")
    assert not line_looks_garbled("这是正常中文文本")
    assert not line_looks_garbled("<color=#FF6B00>{0}</color> 秒后复活")

    assert not has_extract_content("text\n")
    assert not has_extract_content("")
    assert has_extract_content(config.DECRYPT_FAIL_TEXT)
    assert has_extract_content("text\n真实一行\n")

    assert check_csv_quality("text\n") is not None
    assert check_csv_quality("text\n").kind == "empty"
    assert check_csv_quality("") is not None and check_csv_quality("").kind == "empty"

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

    ctrl_body = "\n".join(
        [f"\x7f对话残留{i}" for i in range(config.CSV_GARBLE_MIN_LINES + 1)]
        + good_lines
    )
    assert check_csv_quality(ctrl_body) is not None
    assert check_csv_quality(ctrl_body).kind == "garbled"

    assert check_csv_quality(config.DECRYPT_FAIL_TEXT) is None
    assert match_terminal_status(config.DECRYPT_FAIL_TEXT) == "decrypt_failed"
    assert (
        match_terminal_status(config.ASSETS_MISSING_TEXT + "（无配表）")
        == "assets_missing"
    )
    assert check_csv_quality(config.ASSETS_MISSING_TEXT) is None

    halluc = config.ASSETS_MISSING_TEXT + "\n真实任务文本一行\n"
    assert match_terminal_status(halluc) is None
    assert check_csv_quality(halluc) is not None

    words = frozenset({"色情论坛", "一夜性网", "女神教"})
    raw = "任务说明\n色情论坛\n正常文本\n一夜性网\n包含色情论坛的长句\n短行\n"
    filtered, removed = filter_sensitive_lines(raw, words=words)
    assert removed == 2
    assert filtered.splitlines() == ["任务说明", "正常文本", "包含色情论坛的长句", "短行"]
    hit = scan_sensitive_hits(raw, words=words)
    assert hit.hit_lines == 2
    assert hit.hit_lines < config.SENSITIVE_HIT_MIN
    # 整行全等才算命中：行内包含敏感词不算
    nested = "[女神教] 大祭師\n女神教信徒\n女神教\n"
    nested_hit = scan_sensitive_hits(nested, words=words)
    assert nested_hit.hit_lines == 1
    assert nested_hit.samples == ("女神教",)
    nested_filtered, nested_removed = filter_sensitive_lines(nested, words=words)
    assert nested_removed == 1
    assert nested_filtered.splitlines() == ["[女神教] 大祭師", "女神教信徒"]
    many = "\n".join(["色情论坛"] * config.SENSITIVE_HIT_MIN)
    assert scan_sensitive_hits(many, words=words).hit_lines >= config.SENSITIVE_HIT_MIN
    print("CSV_QUALITY_OK", flush=True)


def test_workspace_markers():
    _ensure_auto_extract_imports()
    import config
    from shared.archive_contract import (
        has_stop,
        mark_stop,
        reset_task_workspace,
        rmtree_force,
    )

    key = "_smoke_markers"
    root = reset_task_workspace(config.WORKSPACE_ROOT, key)
    assert not has_stop(root)
    mark_stop(root)
    assert has_stop(root)

    root2 = reset_task_workspace(config.WORKSPACE_ROOT, key)
    assert root2 == root
    assert not has_stop(root2)
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
