from __future__ import annotations

from typing import Any, Sequence

SYSTEM_PROMPT = """你是 Android 游戏启动引导助手。
目标：自行判断并推进界面，直到出现需要输入账号/密码的登录页，然后调用 done(scene=\"login\")。

每轮给你的是当前截屏的 OCR 结果：屏幕上识别到的可见文字块列表。
每条形如 [id] text='…' x=… y=…：
- text：该文字块内容（按钮文案、标题、提示等）
- x,y：该文字块中心点在屏幕上的坐标，已对齐 adb tap；tap_item(id) 即点这个位置
- note/hints：正则旁注，仅供参考，以你看到的 OCR 为准

每轮只用一个工具后立即结束：
- tap_item(item_id)：点击对应文字块
- wait：下载/加载/看不清时等待
- done(scene)：到达登录页用 login；勿在登录前结束
不要点「不同意/拒绝」；不要输入账号密码；不要编造 id。"""

PING_PROMPT = "Reply with exactly one token: OK or pong. No other text."

# Kept for tests / docs; bootstrap no longer sends this to the API.
TASK_BOOTSTRAP = """推进到需要输入账号/密码的登录页后调用 done(scene=\"login\")。
输入是截屏 OCR 文字块（text + 中心坐标）；tap_item 点对应 id。
工具：tap_item / wait / done。不要点不同意；不要编造 id。"""


def format_ocr_user_message(
    items: Sequence[Any],
    *,
    poll: int,
    note: str = "",
) -> str:
    lines = [
        f"poll={poll} 当前截屏 OCR（每条是屏幕上的一块可见文字及其中心坐标）：",
    ]
    if note:
        lines.append(f"note: {note}")
    if not items:
        lines.append("(no OCR text)")
    else:
        for i, item in enumerate(items):
            text = (getattr(item, "text", "") or "").replace("\n", " ").strip()
            cx = int(getattr(item, "cx", 0) or 0)
            cy = int(getattr(item, "cy", 0) or 0)
            lines.append(f"[{i}] text={text!r} x={cx} y={cy}")
    lines.append("Call exactly ONE tool: tap_item / wait / done. Then stop.")
    return "\n".join(lines)
