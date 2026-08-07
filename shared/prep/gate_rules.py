"""Local OCR rules for prep gate — prefer these over LLM when unambiguous."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from shared.prep.ocr_util import find_tap_for_texts, texts_joined

# Longer / more specific first so find_tap_for_texts prefers real buttons.
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

# (needle, scene) — short button-like labels only.
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


class _TapDevice(Protocol):
    def tap(self, x: int, y: int) -> None: ...


@dataclass(frozen=True)
class LocalGateAction:
    kind: str  # tap | wait | done
    scene: str = ""
    text: str = ""


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


def _short_button_hit(items: Sequence[Any], needle: str, *, max_len: int = 16) -> bool:
    needle_l = needle.lower()
    for item in items:
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        text_l = text.lower()
        if text_l == needle_l:
            return True
        if len(text) <= max_len and needle_l in text_l:
            if text_l.startswith(needle_l) or text_l.endswith(needle_l):
                return True
    return False


def match_entry_scene(items: Sequence[Any]) -> str | None:
    for needle, scene in _ENTRY_NEEDLES:
        if _short_button_hit(items, needle):
            return scene
    return None


def _actionable_items(items: Sequence[Any]) -> list[Any]:
    """Drop deny/reject labels so needle '同意' cannot match '不同意'."""
    out: list[Any] = []
    for item in items:
        text = (getattr(item, "text", "") or "").strip()
        if any(m in text for m in _DENY_MARKERS):
            continue
        out.append(item)
    return out


def is_progress_screen(items: Sequence[Any]) -> bool:
    """True when screen looks like download/update and has no clear action button."""
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


def try_local_action(adb: _TapDevice, items: Sequence[Any]) -> LocalGateAction | None:
    """
    Apply an unambiguous local action.
    Returns LocalGateAction, or None when the frame should fall through to LLM.
    """
    item_list = list(items)
    scene = match_entry_scene(item_list)
    if scene:
        return LocalGateAction(kind="done", scene=scene)

    actionable = _actionable_items(item_list)
    short_buttons = [
        i
        for i in actionable
        if len((getattr(i, "text", "") or "").strip()) <= 10
    ]
    blob = texts_joined(item_list)
    if _RESTART_HINT.search(blob):
        pt = find_tap_for_texts(short_buttons, _RESTART_NEEDLES)
        if pt is not None:
            adb.tap(*pt)
            return LocalGateAction(kind="tap", text="restart_confirm")

    pt = find_tap_for_texts(actionable, _AGREE_NEEDLES)
    if pt is not None:
        adb.tap(*pt)
        return LocalGateAction(kind="tap", text="agree")

    if is_progress_screen(item_list):
        return LocalGateAction(kind="wait", text="progress")

    return None
