from __future__ import annotations

from typing import Any, Sequence

SYSTEM_PROMPT = """你是 Android 游戏启动引导助手。
目标：处理启动时的隐私弹窗与资源下载/更新，直到到达登录、开始游戏或选服界面。
禁止进入登录后操作；禁止点击「不同意」；不确定时调用 wait。
硬性规则：每一轮用户消息只调用恰好一个工具（tap_item 或 wait 或 done），调用后立即结束，禁止连续多次工具调用。"""

PING_PROMPT = "Reply with exactly one token: OK or pong. No other text."

TASK_BOOTSTRAP = """工作说明（请记住，后续轮次只追加当前画面 OCR）：
1. 每轮会给你编号 OCR 列表：id / text / x / y（坐标已对齐 adb tap）。
2. 你的任务：同意隐私、推进资源下载；到达登录/开始游戏/选服时调用 done。
3. 工具（每轮只用一个）：
   - tap_item(item_id)：点击对应 OCR 项中心
   - wait：下载中、动画中、OCR 过少/看不清时等待
   - done(scene)：scene 只能是 login / start_game / server_select / entry
4. 不要点「不同意」「拒绝」；不要编造不存在的 id。
请简短确认你已理解（一句话即可，不要调用工具）。"""


def format_ocr_user_message(
    items: Sequence[Any],
    *,
    poll: int,
    note: str = "",
) -> str:
    lines = [f"poll={poll} current screen OCR:"]
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
    lines.append("Call exactly ONE tool now: tap_item / wait / done. Then stop.")
    return "\n".join(lines)
