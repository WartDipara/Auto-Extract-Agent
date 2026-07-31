"""Unit tests for result CSV simplified/traditional split."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "apps" / "auto-extract" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def test_route_known_samples():
    from zh_script import route_bucket

    assert route_bucket("你好呀，我以爲你是來找我的呢！") == "t"
    assert route_bucket("你好呀，我以为你是来找我的呢！") == "s"


def test_split_pure_simplified_is_pure():
    from zh_script import split_body_text

    body = "跨服好友\n(废弃)云渊传说碎片\n"
    split = split_body_text(body)
    assert split.traditional_lines == []
    assert split.is_pure is True
    assert len(split.simplified_lines) >= 1


def test_split_mixed_not_pure():
    from zh_script import join_csv_body, split_body_text

    body = (
        "你好呀，我以为你是来找我的呢！\n"
        "你好呀，我以爲你是來找我的呢！\n"
    )
    split = split_body_text(body)
    assert split.is_pure is False
    assert split.simplified_lines == ["你好呀，我以为你是来找我的呢！"]
    assert split.traditional_lines == ["你好呀，我以爲你是來找我的呢！"]
    assert join_csv_body(split.simplified_lines).endswith("\n")
    assert len(split.simplified_lines) + len(split.traditional_lines) == 2


def test_archive_csv_pure_keeps_single(tmp_path, monkeypatch):
    import config
    import extract_bridge as eb

    monkeypatch.setattr(config, "RESULT_DIR", tmp_path)
    body = "你好呀，我以为你是来找我的呢！\n(废弃)云渊传说碎片\n"
    dest = eb.archive_csv(tmp_path / "tests.csv", "demo", "纯简游戏", body)
    assert dest.name == "demo_纯简游戏.csv"
    assert dest.read_text(encoding="utf-8-sig") == body
    assert not (tmp_path / "demo_纯简游戏_T.csv").exists()


def test_archive_csv_mixed_writes_two(tmp_path, monkeypatch):
    import config
    import extract_bridge as eb

    monkeypatch.setattr(config, "RESULT_DIR", tmp_path)
    body = (
        "你好呀，我以为你是来找我的呢！\n"
        "你好呀，我以爲你是來找我的呢！\n"
    )
    dest = eb.archive_csv(tmp_path / "tests.csv", "demo", "混用", body)
    dest_t = tmp_path / "demo_混用_T.csv"
    assert dest.name == "demo_混用.csv"
    assert dest_t.is_file()
    assert "以为" in dest.read_text(encoding="utf-8-sig")
    assert "以爲" not in dest.read_text(encoding="utf-8-sig")
    assert "以爲" in dest_t.read_text(encoding="utf-8-sig")
    assert "以为" not in dest_t.read_text(encoding="utf-8-sig")


if __name__ == "__main__":
    test_route_known_samples()
    test_split_pure_simplified_is_pure()
    test_split_mixed_not_pure()
    print("ZH_SCRIPT_UNIT_OK")
