"""OCR + regex recognition helpers for prep gate.

These produce advisory hints only. They must never tap or declare entry done;
the LLM owns all decisions.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Sequence

from shared.prep.ocr_util import find_tap_for_texts, texts_joined

_AGREE_NEEDLES = (
    "同意并继续",
    "同意并进入",
    "同意并接受",
    "我已阅读并同意",
    "我同意",
    "同意",
    "接受",
    "允许",
)

_DENY_MARKERS = ("不同意", "拒绝", "暂不")

_ENTRY_TITLE_BLOCK = (
    "欢迎",
    "温馨",
    "协议",
    "隐私",
    "政策",
    "服务条款",
    "个人信息",
)

_PRIVACY_SCREEN_MARKERS = (
    "温馨提示",
    "隐私政策",
    "用户服务协议",
    "用户隐私政策",
    "个人信息保护",
)

_ENTRY_NEEDLES: tuple[tuple[str, str], ...] = (
    ("进入游戏", "start_game"),
    ("开始游戏", "start_game"),
    ("立即进入", "start_game"),
    ("选服", "server_select"),
    ("选择服务器", "server_select"),
    ("服务器列表", "server_select"),
    ("登录", "login"),
    ("登入", "login"),
    ("账号登录", "login"),
)

_RESTART_HINT = re.compile(
    r"(更新完成|手动重启|重新启动|请退出|退出后|重启游戏|请重新)"
)
_RESTART_NEEDLES = ("重新启动", "立即重启", "重启", "知道了", "确定", "好的")

_PROGRESS_RE = re.compile(
    r"(下载中|正在下载|资源下载|正在更新|更新中|加载中|解压中|"
    r"请稍候|请耐心|剩余|预计|下载资源|更新资源|"
    r"\d+\s*%)"
)

_DIGIT_RE = re.compile(r"\d+")
_SPACE_RE = re.compile(r"\s+")


def content_fingerprint(items: Sequence[Any]) -> str:
    """Fingerprint that ignores progress digits so 12%→13% does not re-query LLM."""
    parts: list[str] = []
    for item in items:
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        text = _DIGIT_RE.sub("#", text)
        text = _SPACE_RE.sub("", text)
        parts.append(text)
    blob = "\n".join(parts)
    return hashlib.sha1(blob.encode("utf-8", errors="replace")).hexdigest()


def _actionable_items(items: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    for item in items:
        text = (getattr(item, "text", "") or "").strip()
        if any(m in text for m in _DENY_MARKERS):
            continue
        out.append(item)
    return out


def _entry_button_hit(items: Sequence[Any], needle: str) -> bool:
    needle_l = needle.lower()
    for item in items:
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        if any(b in text for b in _ENTRY_TITLE_BLOCK):
            continue
        text_l = text.lower()
        if text_l == needle_l:
            return True
        if len(text) <= len(needle) + 2 and needle_l in text_l:
            if text_l.startswith(needle_l) or text_l.endswith(needle_l):
                return True
    return False


def match_entry_scene(items: Sequence[Any]) -> str | None:
    for needle, scene in _ENTRY_NEEDLES:
        if _entry_button_hit(items, needle):
            return scene
    return None


def looks_like_privacy_consent(items: Sequence[Any]) -> bool:
    blob = texts_joined(list(items))
    if any(m in blob for m in _PRIVACY_SCREEN_MARKERS):
        return True
    if any(m in blob for m in _DENY_MARKERS) and find_tap_for_texts(
        _actionable_items(items), _AGREE_NEEDLES
    ):
        return True
    return False


def is_progress_screen(items: Sequence[Any]) -> bool:
    blob = texts_joined(list(items))
    if not _PROGRESS_RE.search(blob):
        return False
    if match_entry_scene(items):
        return False
    actionable = _actionable_items(items)
    if find_tap_for_texts(actionable, _AGREE_NEEDLES):
        return False
    if _RESTART_HINT.search(blob) and find_tap_for_texts(
        [i for i in actionable if len((getattr(i, "text", "") or "").strip()) <= 10],
        _RESTART_NEEDLES,
    ):
        return False
    return True


def _item_ids_matching(items: Sequence[Any], needles: Sequence[str]) -> list[int]:
    ids: list[int] = []
    for i, item in enumerate(items):
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        if any(m in text for m in _DENY_MARKERS):
            continue
        for needle in needles:
            if text == needle or (len(text) <= 12 and needle in text):
                ids.append(i)
                break
    return ids


def build_ocr_hints(items: Sequence[Any]) -> str:
    """
    Advisory regex observations for the LLM.
    Never executes taps or marks entry reached.
    """
    hints: list[str] = []
    if looks_like_privacy_consent(items):
        hints.append(
            "privacy/consent dialog likely — prefer tap 同意; do NOT done yet"
        )
    agree_ids = _item_ids_matching(items, _AGREE_NEEDLES)
    if agree_ids:
        hints.append(f"possible agree button ids={agree_ids}")
    deny_ids = [
        i
        for i, item in enumerate(items)
        if any(m in (getattr(item, "text", "") or "") for m in _DENY_MARKERS)
    ]
    if deny_ids:
        hints.append(f"deny/reject labels ids={deny_ids} (do not tap)")

    blob = texts_joined(list(items))
    if _RESTART_HINT.search(blob):
        restart_ids = _item_ids_matching(items, _RESTART_NEEDLES)
        hints.append(
            "update/restart prompt likely"
            + (f"; confirm ids={restart_ids}" if restart_ids else "")
        )

    if is_progress_screen(items):
        hints.append("download/progress screen likely → wait")

    scene = match_entry_scene(items)
    if scene:
        hints.append(
            f"possible entry match scene={scene} "
            "(verify real button, not title like 欢迎进入游戏)"
        )
    elif any("进入游戏" in (getattr(item, "text", "") or "") for item in items):
        hints.append(
            "saw 进入游戏 inside longer text — likely title, not entry button"
        )

    if not hints:
        return ""
    return "regex hints (advisory only): " + "; ".join(hints)
