"""Prep robustness: install/hotfix/OCR soft-fail; extract continues on decoded."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]
_A_APP = _ROOT / "apps" / "auto-extract"
_A_SRC = _A_APP / "src"
for p in (_ROOT, _A_SRC, _A_APP):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _purge():
    for p in list(sys.path):
        if "im-module" in p.replace("\\", "/"):
            sys.path.remove(p)
    for name in ("config", "prep_stages", "errors", "errors.model"):
        sys.modules.pop(name, None)


def test_hotfix_has_content_oserror_soft(tmp_path):
    from shared.prep import hotfix_pull

    boom = MagicMock()
    boom.is_dir.return_value = True
    boom.rglob.side_effect = OSError("disk gone")
    assert hotfix_pull.hotfix_has_content(boom) is False


def test_pull_hotfix_never_raises(tmp_path):
    from shared.prep import hotfix_pull

    adb = MagicMock()
    original_run = hotfix_pull._try_pull_run_as
    original_sd = hotfix_pull._try_pull_android_data
    hotfix_pull._try_pull_run_as = MagicMock(side_effect=RuntimeError("x"))
    hotfix_pull._try_pull_android_data = MagicMock(side_effect=NameError("y"))
    try:
        out = tmp_path / "hf"
        assert hotfix_pull.pull_hotfix_candidates(adb, "pkg", out) == "error"
        assert out.is_dir()
    finally:
        hotfix_pull._try_pull_run_as = original_run
        hotfix_pull._try_pull_android_data = original_sd


def test_run_device_stage_install_soft_fail(tmp_path, monkeypatch):
    _purge()
    import prep_stages as ps

    apk = tmp_path / "game.apk"
    apk.write_bytes(b"apk")
    signed = tmp_path / "game_signed.apk"
    signed.write_bytes(b"signed")
    (tmp_path / "decoded").mkdir()
    (tmp_path / "hotfix").mkdir()

    adb = MagicMock()
    adb.serial = "s1"
    adb.device_handler = MagicMock(name="default")
    adb.ensure_uninstalled.return_value = False

    monkeypatch.setattr(ps, "AdbDevice", lambda serial: adb)
    monkeypatch.setattr(
        ps,
        "dispatch_device",
        lambda _adb: MagicMock(
            install_apk=MagicMock(side_effect=RuntimeError("install fail"))
        ),
    )
    monkeypatch.setattr(
        ps,
        "task_layout",
        lambda root: {
            "decoded": Path(root) / "decoded",
            "hotfix": Path(root) / "hotfix",
        },
    )
    pull = MagicMock()
    monkeypatch.setattr(ps, "pull_hotfix_candidates", pull)

    result = ps.run_device_stage(
        task_root=tmp_path,
        apk_path=apk,
        signed_apk=signed,
        package_name="pkg.demo",
        serial="s1",
        skip_ocr_gate=True,
    )
    assert result.hotfix_has_files is False
    assert result.pull_source == "none"
    assert result.screen_reached == "install_failed"
    pull.assert_not_called()


def test_run_device_stage_gate_and_pull_soft(tmp_path, monkeypatch):
    _purge()
    import prep_stages as ps

    apk = tmp_path / "game.apk"
    apk.write_bytes(b"apk")
    signed = tmp_path / "game_signed.apk"
    signed.write_bytes(b"signed")
    (tmp_path / "decoded").mkdir()
    (tmp_path / "hotfix").mkdir()

    adb = MagicMock()
    adb.serial = "s1"
    adb.device_handler = MagicMock(name="default")
    adb.launch_package.side_effect = RuntimeError("launch boom")
    adb.force_stop.side_effect = RuntimeError("stop boom")

    calls = {"n": 0}

    def _ensure(_pkg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd="pm", timeout=1)
        return False

    adb.ensure_uninstalled = _ensure

    monkeypatch.setattr(ps, "AdbDevice", lambda serial: adb)
    monkeypatch.setattr(
        ps,
        "dispatch_device",
        lambda _adb: MagicMock(install_apk=MagicMock(return_value=None)),
    )
    monkeypatch.setattr(
        ps,
        "wait_until_entry_screen",
        MagicMock(side_effect=RuntimeError("gate boom")),
    )
    monkeypatch.setattr(
        ps, "pull_hotfix_candidates", MagicMock(return_value="error")
    )
    monkeypatch.setattr(ps, "hotfix_has_content", MagicMock(return_value=False))
    monkeypatch.setattr(
        ps,
        "task_layout",
        lambda root: {
            "decoded": Path(root) / "decoded",
            "hotfix": Path(root) / "hotfix",
        },
    )

    result = ps.run_device_stage(
        task_root=tmp_path,
        apk_path=apk,
        signed_apk=signed,
        package_name="pkg.demo",
        serial="s1",
        skip_ocr_gate=False,
    )
    assert result.hotfix_has_files is False
    assert result.pull_source == "error"
    assert result.screen_reached == "gate_error"
