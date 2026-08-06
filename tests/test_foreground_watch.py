"""Unit tests for ForegroundWatch debounce (no device)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "apps" / "auto-extract" / "src"
for _p in (_SRC, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.prep.foreground_watch import ForegroundState, ForegroundWatch


class _FakeAdb:
    def __init__(self):
        self.running = True
        self.focused = "com.demo.game"

    def is_package_running(self, package: str) -> bool:
        return self.running

    def foreground_package(self) -> str:
        return self.focused

    def bring_to_foreground(self, package: str) -> None:
        self.focused = package


def test_splash_focus_gap_does_not_crash_or_bring_back():
    adb = _FakeAdb()
    watch = ForegroundWatch(
        adb,  # type: ignore[arg-type]
        "com.demo.game",
        crash_confirm=3,
        background_confirm=2,
    )

    # Same-package Splash handoff: focus briefly empty / other, then back.
    adb.focused = ""
    assert watch.poll() is ForegroundState.FOREGROUND
    assert watch.apply() is None

    adb.focused = "app.lawnchair"
    assert watch.poll() is ForegroundState.FOREGROUND  # 1/2 gap
    assert watch.apply() is None

    adb.focused = "com.demo.game"
    assert watch.poll() is ForegroundState.FOREGROUND
    assert watch.apply() is None


def test_brief_process_gap_needs_confirmations():
    adb = _FakeAdb()
    watch = ForegroundWatch(
        adb,  # type: ignore[arg-type]
        "com.demo.game",
        crash_confirm=3,
        background_confirm=2,
    )

    adb.running = False
    assert watch.poll() is ForegroundState.FOREGROUND  # 1/3
    assert watch.apply() is None
    assert watch.poll() is ForegroundState.FOREGROUND  # 2/3
    assert watch.apply() is None

    # Process comes back (self-restart) → counter clears.
    adb.running = True
    assert watch.poll() is ForegroundState.FOREGROUND
    assert watch.apply() is None

    adb.running = False
    assert watch.poll() is ForegroundState.FOREGROUND
    assert watch.poll() is ForegroundState.FOREGROUND
    assert watch.poll() is ForegroundState.CRASHED
    assert watch.apply() == "crash"


def test_sustained_background_brings_back():
    adb = _FakeAdb()
    watch = ForegroundWatch(
        adb,  # type: ignore[arg-type]
        "com.demo.game",
        crash_confirm=3,
        background_confirm=2,
    )
    adb.focused = "com.android.settings"
    assert watch.poll() is ForegroundState.FOREGROUND
    assert watch.poll() is ForegroundState.BACKGROUNDED
    assert watch.apply() == "brought_back"
    assert adb.focused == "com.demo.game"
