"""Unit tests for prep gate local rules (no LLM)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "apps" / "auto-extract"
_SRC = _APP / "src"
for p in (_APP, _SRC, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@dataclass
class FakeOcr:
    text: str
    cx: int
    cy: int


class FakeAdb:
    def __init__(self):
        self.taps: list[tuple[int, int]] = []

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))


def test_agree_taps_short_button_not_deny():
    from shared.prep.gate_rules import try_local_action

    adb = FakeAdb()
    items = [
        FakeOcr("详细阅读并同意本协议全部条款", 10, 10),
        FakeOcr("不同意", 50, 200),
        FakeOcr("同意", 200, 200),
    ]
    out = try_local_action(adb, items)
    assert out is not None and out.kind == "tap" and out.text == "agree"
    assert adb.taps == [(200, 200)]


def test_entry_done_login():
    from shared.prep.gate_rules import try_local_action

    adb = FakeAdb()
    out = try_local_action(adb, [FakeOcr("登录", 100, 100)])
    assert out is not None and out.kind == "done" and out.scene == "login"
    assert adb.taps == []


def test_progress_waits_without_llm():
    from shared.prep.gate_rules import (
        content_fingerprint,
        is_progress_screen,
        try_local_action,
    )

    items_a = [FakeOcr("资源下载中", 1, 1), FakeOcr("12%", 2, 2)]
    items_b = [FakeOcr("资源下载中", 1, 1), FakeOcr("48%", 2, 2)]
    assert is_progress_screen(items_a)
    assert content_fingerprint(items_a) == content_fingerprint(items_b)

    adb = FakeAdb()
    out = try_local_action(adb, items_a)
    assert out is not None and out.kind == "wait"
    assert adb.taps == []


def test_progress_with_agree_still_taps():
    from shared.prep.gate_rules import try_local_action

    adb = FakeAdb()
    items = [FakeOcr("下载中 3%", 1, 1), FakeOcr("同意", 100, 200)]
    out = try_local_action(adb, items)
    assert out is not None and out.kind == "tap"
    assert adb.taps == [(100, 200)]


def test_restart_confirm_tap():
    from shared.prep.gate_rules import try_local_action

    adb = FakeAdb()
    items = [
        FakeOcr("更新完成，请退出后重新启动", 10, 10),
        FakeOcr("确定", 100, 300),
    ]
    out = try_local_action(adb, items)
    assert out is not None and out.kind == "tap" and out.text == "restart_confirm"
    assert adb.taps == [(100, 300)]


def test_ambiguous_falls_through():
    from shared.prep.gate_rules import try_local_action

    adb = FakeAdb()
    out = try_local_action(
        adb,
        [FakeOcr("点击领取礼包", 10, 10), FakeOcr("活动中心", 20, 20)],
    )
    assert out is None
    assert adb.taps == []
