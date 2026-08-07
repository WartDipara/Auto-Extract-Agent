"""Unit tests for prep gate OCR/regex hints (no local decisions)."""

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


def test_privacy_welcome_hints_not_entry():
    from shared.prep.gate_rules import build_ocr_hints, match_entry_scene

    items = [
        FakeOcr("温馨提示", 10, 10),
        FakeOcr("欢迎进入游戏", 10, 40),
        FakeOcr(
            "1.为给您提供游戏资源加载服务，我们可能会申请手机存储权限",
            10,
            80,
        ),
        FakeOcr("不同意", 80, 400),
        FakeOcr("同意", 220, 400),
    ]
    assert match_entry_scene(items) is None
    hints = build_ocr_hints(items)
    assert "privacy" in hints or "consent" in hints
    assert "agree" in hints
    assert "do NOT done" in hints
    assert "欢迎进入游戏" in hints or "title" in hints or "进入游戏" in hints


def test_real_enter_game_hint_possible_entry():
    from shared.prep.gate_rules import build_ocr_hints, match_entry_scene

    items = [FakeOcr("进入游戏", 100, 300)]
    assert match_entry_scene(items) == "start_game"
    hints = build_ocr_hints(items)
    assert "start_game" in hints
    assert "advisory" in hints


def test_progress_hint_suggests_wait():
    from shared.prep.gate_rules import build_ocr_hints, content_fingerprint, is_progress_screen

    items_a = [FakeOcr("资源下载中", 1, 1), FakeOcr("12%", 2, 2)]
    items_b = [FakeOcr("资源下载中", 1, 1), FakeOcr("48%", 2, 2)]
    assert is_progress_screen(items_a)
    assert content_fingerprint(items_a) == content_fingerprint(items_b)
    hints = build_ocr_hints(items_a)
    assert "wait" in hints


def test_login_hint():
    from shared.prep.gate_rules import build_ocr_hints, match_entry_scene

    items = [FakeOcr("登录", 100, 100)]
    assert match_entry_scene(items) == "login"
    assert "login" in build_ocr_hints(items)


def test_hints_never_tap():
    """Recognition helpers must not expose tap/done actions."""
    import shared.prep.gate_rules as gr

    assert not hasattr(gr, "try_local_action")
    assert callable(gr.build_ocr_hints)
