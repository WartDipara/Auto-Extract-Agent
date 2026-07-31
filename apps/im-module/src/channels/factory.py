"""Route IM_CHANNEL env value to a Channel implementation (open for new adapters)."""

from __future__ import annotations

import os

from channels.base import Channel


def create_channel(name: str) -> Channel:
    key = (name or "").strip().lower()
    if key in ("feishu", "lark"):
        from channels.feishu import FeishuChannel

        app_id = os.environ.get("FEISHU_APP_ID", "").strip()
        app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
        if not app_id or not app_secret:
            raise SystemExit("set FEISHU_APP_ID and FEISHU_APP_SECRET")
        return FeishuChannel(app_id, app_secret)
    if key in ("dingtalk", "dingding"):
        raise SystemExit(
            f"IM_CHANNEL={name!r} reserved; add channels/dingtalk.py then register here"
        )
    raise SystemExit(f"unknown IM_CHANNEL={name!r}; use feishu | dingtalk")
