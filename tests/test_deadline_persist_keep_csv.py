"""deadline_persist must not overwrite a successful tests.csv."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "apps" / "auto-extract"
_SRC = _APP / "src"


def _reload_auto_extract():
    for p in (str(_SRC), str(_APP), str(_ROOT)):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in (
        "config",
        "extract_bridge",
        "opencode_session",
        "prompts",
        "csv_quality",
    ):
        sys.modules.pop(name, None)


@pytest.fixture()
def eb(tmp_path, monkeypatch):
    _reload_auto_extract()
    import config
    import extract_bridge
    import prompts as prompt_store
    from shared.archive_contract import reset_task_workspace

    prompt_store.load_prompts(force_reload=True)
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path / "ws")
    root = reset_task_workspace(config.WORKSPACE_ROOT, "deadline_keep")
    extract_bridge._task_root = root
    return extract_bridge, root


def test_write_decrypt_fail_preserves_real_extract(eb):
    extract_bridge, root = eb
    csv_path = root / "outputs" / "tests.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    body = "text\n" + "\n".join(f"行{i}" for i in range(100)) + "\n"
    csv_path.write_text(body, encoding="utf-8-sig")

    out = extract_bridge.write_decrypt_fail_csv(
        "demo.apk", reason="已满一小时，催促落盘后仍判定为解密失败"
    )
    assert out == csv_path
    text = csv_path.read_text(encoding="utf-8-sig")
    assert "行0" in text
    assert "行99" in text
    assert "解密失败" not in text


def test_write_decrypt_fail_writes_when_empty(eb):
    extract_bridge, root = eb
    csv_path = root / "outputs" / "tests.csv"
    assert not csv_path.is_file()

    extract_bridge.write_decrypt_fail_csv("demo.apk", reason="仍无有效 tests.csv")
    text = csv_path.read_text(encoding="utf-8-sig")
    assert "解密失败" in text
    assert "仍无有效" in text


def test_deadline_persist_keeps_agent_written_csv(eb, monkeypatch):
    extract_bridge, root = eb
    csv_path = root / "outputs" / "tests.csv"
    (root / "decoded").mkdir(parents=True, exist_ok=True)
    (root / "hotfix").mkdir(parents=True, exist_ok=True)
    (root / "decoded" / "AndroidManifest.xml").write_text("<manifest/>", encoding="utf-8")

    calls: list[str] = []

    def fake_run(*, task_key, prompt, cwd, skill, force_new, print_live,
                 stall_sec, stall_output_path, hard_timeout_sec, stop_path):
        phase_hint = "initial"
        if "半小时" in prompt:
            phase_hint = "stall_continue"
        elif "一小时" in prompt or "落盘" in prompt:
            phase_hint = "deadline_persist"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text(
                "text\n真实提取一行\n真实提取二行\n",
                encoding="utf-8-sig",
            )
        calls.append(phase_hint)
        stalled = phase_hint in ("initial", "stall_continue")
        return SimpleNamespace(
            returncode=0,
            stdout_text="",
            session_id="ses-deadline",
            stalled=stalled,
            kill_reason="stall" if stalled else None,
        )

    class _FakeMgr:
        def run(self, **kwargs):
            return fake_run(**kwargs)

        def lookup_session_id(self, task_key):
            return "ses-deadline"

    monkeypatch.setattr(
        extract_bridge, "OpenCodeSessionManager", lambda: _FakeMgr()
    )
    monkeypatch.setattr(
        extract_bridge, "export_session_json", lambda *a, **k: None
    )
    monkeypatch.setattr(
        extract_bridge, "_ask_final_csv_review", lambda *a, **k: None
    )
    monkeypatch.setattr(
        extract_bridge, "_resume_quality_gate", lambda *a, **k: None
    )
    monkeypatch.setattr(
        extract_bridge, "_ask_large_csv_review", lambda *a, **k: None
    )

    extract_bridge.invoke_opencode("demo.apk", task_root=root)

    assert "deadline_persist" in calls
    text = csv_path.read_text(encoding="utf-8-sig")
    assert "真实提取一行" in text
    assert "解密失败" not in text
