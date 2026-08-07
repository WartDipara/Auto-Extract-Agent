from __future__ import annotations

from typing import Any

from channels.base import Channel
from channels.dingtalk import DingTalkChannel
from channels.feishu import FeishuChannel


def create_channel(cfg: Any) -> Channel:
    key = (getattr(cfg, "IM_CHANNEL", "") or "").strip().lower()
    if key in ("feishu", "lark"):
        app_id = (getattr(cfg, "FEISHU_APP_ID", "") or "").strip()
        app_secret = (getattr(cfg, "FEISHU_APP_SECRET", "") or "").strip()
        if not app_id or not app_secret:
            raise SystemExit("set FEISHU_APP_ID and FEISHU_APP_SECRET")
        return FeishuChannel(app_id, app_secret)
    if key in ("dingtalk", "dingding"):
        client_id = (getattr(cfg, "DINGTALK_CLIENT_ID", "") or "").strip()
        client_secret = (getattr(cfg, "DINGTALK_CLIENT_SECRET", "") or "").strip()
        robot_code = (getattr(cfg, "DINGTALK_ROBOT_CODE", "") or "").strip() or None
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
    raise SystemExit(f"unknown IM_CHANNEL={key!r}; use feishu | dingtalk")
