"""Hotfix exclude constants + foreground watch reset after relaunch."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]
_CORE_SRC = _ROOT / "apps" / "auto-extract" / "src"
for _p in (_ROOT, _CORE_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_data_exclude_prefixes_defined():
    from shared.prep.hotfix_pull import _DATA_EXCLUDE_PREFIXES, _excluded

    assert "ShadowPlugin" in _DATA_EXCLUDE_PREFIXES
    assert _excluded("ShadowPluginManager", sdcard=False) is True
    assert _excluded("crashsdk", sdcard=False) is True
    assert _excluded("assets", sdcard=False) is False


def test_pull_hotfix_candidates_soft_fails():
    from shared.prep import hotfix_pull

    adb = MagicMock()
    out = Path("tmp_hotfix_soft_fail_test")
    try:
        # Force unexpected failure inside pull path.
        original = hotfix_pull._try_pull_run_as
        hotfix_pull._try_pull_run_as = MagicMock(side_effect=NameError("boom"))
        try:
            source = hotfix_pull.pull_hotfix_candidates(adb, "pkg.demo", out)
        finally:
            hotfix_pull._try_pull_run_as = original
        assert source == "error"
        assert out.is_dir()
    finally:
        if out.exists():
            import shutil

            shutil.rmtree(out, ignore_errors=True)


def test_foreground_watch_reset_restarts_thread():
    from shared.prep.foreground_watch import ForegroundState, ForegroundWatch

    adb = MagicMock()
    adb.is_package_running.return_value = False
    adb.foreground_package.return_value = ""
    watch = ForegroundWatch(adb, "pkg.demo", poll_sec=0.05, crash_confirm=1)
    watch.start()
    # Drive into crashed so background thread exits.
    assert watch.poll() is ForegroundState.CRASHED
    assert watch.apply(ForegroundState.CRASHED) == "crash"
    watch._thread.join(timeout=2.0)
    assert watch._thread is not None
    assert not watch._thread.is_alive()

    adb.is_package_running.return_value = True
    adb.foreground_package.return_value = "pkg.demo"
    watch.reset()
    assert watch.state is ForegroundState.FOREGROUND
    assert watch._thread is not None and watch._thread.is_alive()
    watch.stop()
