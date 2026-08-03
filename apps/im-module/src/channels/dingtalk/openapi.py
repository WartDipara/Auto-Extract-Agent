"""DingTalk OpenAPI helpers (accessToken + robot send).

Docs:
- accessToken: POST /v1.0/oauth2/accessToken
- group send: POST /v1.0/robot/groupMessages/send (msgKey/msgParam)
- oto send: POST /v1.0/robot/oToMessages/batchSend
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

_log = logging.getLogger(__name__)

_OPENAPI = "https://api.dingtalk.com"
# Enterprise robot text template (official msgKey).
MSG_KEY_TEXT = "sampleText"


class DingTalkOpenApi:
    def __init__(self, client_id: str, client_secret: str, robot_code: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._robot_code = robot_code
        self._token = ""
        self._token_expire_at = 0.0

    def access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expire_at - 60:
            return self._token
        resp = requests.post(
            f"{_OPENAPI}/v1.0/oauth2/accessToken",
            json={
                "appKey": self._client_id,
                "appSecret": self._client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("accessToken") or ""
        if not token:
            raise RuntimeError(f"dingtalk accessToken empty: {data}")
        expire_in = int(data.get("expireIn") or 7200)
        self._token = token
        self._token_expire_at = now + expire_in
        return token

    def send_group_text(self, open_conversation_id: str, text: str) -> dict[str, Any]:
        return self._post_robot(
            "/v1.0/robot/groupMessages/send",
            {
                "robotCode": self._robot_code,
                "openConversationId": open_conversation_id,
                "msgKey": MSG_KEY_TEXT,
                "msgParam": json.dumps({"content": text}, ensure_ascii=False),
            },
        )

    def send_oto_text(self, user_id: str, text: str) -> dict[str, Any]:
        return self._post_robot(
            "/v1.0/robot/oToMessages/batchSend",
            {
                "robotCode": self._robot_code,
                "userIds": [user_id],
                "msgKey": MSG_KEY_TEXT,
                "msgParam": json.dumps({"content": text}, ensure_ascii=False),
            },
        )

    def _post_robot(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        token = self.access_token()
        resp = requests.post(
            f"{_OPENAPI}{path}",
            headers={
                "Content-Type": "application/json",
                "x-acs-dingtalk-access-token": token,
            },
            json=body,
            timeout=30,
        )
        if resp.status_code >= 400:
            _log.error(
                "dingtalk openapi %s failed status=%s body=%s",
                path,
                resp.status_code,
                resp.text[:500],
            )
            resp.raise_for_status()
        data = resp.json() if resp.text else {}
        _log.info("dingtalk openapi %s ok keys=%s", path, list(data.keys()))
        return data
