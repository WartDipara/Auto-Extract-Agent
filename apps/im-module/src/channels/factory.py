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
        from channels.dingtalk import DingTalkChannel

        client_id = (
            os.environ.get("DINGTALK_CLIENT_ID", "").strip()
            or os.environ.get("DINGTALK_APP_KEY", "").strip()
        )
        client_secret = (
            os.environ.get("DINGTALK_CLIENT_SECRET", "").strip()
            or os.environ.get("DINGTALK_APP_SECRET", "").strip()
        )
        robot_code = os.environ.get("DINGTALK_ROBOT_CODE", "").strip() or None
        if not client_id or not client_secret:
            raise SystemExit(
                "set DINGTALK_CLIENT_ID/DINGTALK_CLIENT_SECRET "
                "(aliases: DINGTALK_APP_KEY / DINGTALK_APP_SECRET)"
            )
        return DingTalkChannel(
            client_id,
            client_secret,
            robot_code=robot_code,
        )
    raise SystemExit(f"unknown IM_CHANNEL={name!r}; use feishu | dingtalk")
