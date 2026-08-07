"""Sensitive-word place allowlist smoke tests."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_place_names_not_sensitive():
    from shared.sensitive_words import clear_sensitive_words_cache, load_sensitive_words

    clear_sensitive_words_cache()
    words = load_sensitive_words()
    for name in ("北京", "武汉", "香港", "台湾", "西藏", "新疆", "中国", "日本", "美国"):
        assert name not in words, name


def test_political_landmarks_still_sensitive():
    from shared.sensitive_words import clear_sensitive_words_cache, load_sensitive_words

    clear_sensitive_words_cache()
    words = load_sensitive_words()
    for name in ("天安门", "中南海", "打台湾"):
        assert name in words, name


def test_non_political_game_words_dropped():
    from shared.sensitive_words import clear_sensitive_words_cache, load_sensitive_words

    clear_sensitive_words_cache()
    words = load_sensitive_words()
    for name in ("炸药", "幼龍", "毒刺", "現金", "管理", "色情论坛", "冰毒", "手枪"):
        assert name not in words, name


def test_scan_keeps_places_filters_politics():
    from shared.sensitive_words import clear_sensitive_words_cache, scan_sensitive_hits

    clear_sensitive_words_cache()
    text = "北京\n天安门\n武汉\n打台湾\n炸药\n管理\n"
    hit = scan_sensitive_hits(text)
    assert hit.hit_lines == 2
    assert set(hit.samples) == {"天安门", "打台湾"}


if __name__ == "__main__":
    test_place_names_not_sensitive()
    test_political_landmarks_still_sensitive()
    test_non_political_game_words_dropped()
    test_scan_keeps_places_filters_politics()
    print("PLACE_ALLOWLIST_OK")
