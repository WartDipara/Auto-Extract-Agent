"""Minimal Feishu Bitable HTTP client (tenant_access_token)."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

_log = logging.getLogger(__name__)

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_SEARCH_URL = (
    "https://open.feishu.cn/open-apis/bitable/v1/apps/"
    "{app_token}/tables/{table_id}/records/search"
)
_BATCH_UPDATE_URL = (
    "https://open.feishu.cn/open-apis/bitable/v1/apps/"
    "{app_token}/tables/{table_id}/records/batch_update"
)


class BitableError(RuntimeError):
    pass


class BitableClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        app_token: str,
        table_id: str,
        session: requests.Session | None = None,
    ):
        self._app_id = app_id
        self._app_secret = app_secret
        self._app_token = app_token
        self._table_id = table_id
        self._session = session or requests.Session()
        self._token = ""
        self._token_expire_at = 0.0

    def list_records(self, *, page_size: int = 500) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = ""
        while True:
            body: dict[str, Any] = {"page_size": min(500, max(1, page_size))}
            params: dict[str, Any] = {}
            if page_token:
                params["page_token"] = page_token
            data = self._request(
                "POST",
                _SEARCH_URL.format(
                    app_token=self._app_token, table_id=self._table_id
                ),
                params=params or None,
                json_body=body,
            )
            chunk = data.get("items") or data.get("records") or []
            if isinstance(chunk, list):
                items.extend(chunk)
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                break
        return items

    def batch_update(self, records: list[dict[str, Any]]) -> None:
        """Update records in chunks of 500. records: [{record_id, fields}, ...]."""
        if not records:
            return
        for i in range(0, len(records), 500):
            chunk = records[i : i + 500]
            self._request(
                "POST",
                _BATCH_UPDATE_URL.format(
                    app_token=self._app_token, table_id=self._table_id
                ),
                json_body={"records": chunk},
            )

    def _access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expire_at - 60:
            return self._token
        resp = self._session.post(
            _TOKEN_URL,
            json={"app_id": self._app_id, "app_secret": self._app_secret},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if int(payload.get("code", -1)) != 0:
            raise BitableError(
                f"tenant_access_token failed: {payload.get('msg') or payload}"
            )
        token = str(payload.get("tenant_access_token") or "")
        if not token:
            raise BitableError("tenant_access_token empty")
        expire = int(payload.get("expire") or 7200)
        self._token = token
        self._token_expire_at = now + expire
        return token

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }
        resp = self._session.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
        if int(payload.get("code", -1)) != 0:
            raise BitableError(
                f"bitable api failed code={payload.get('code')} msg={payload.get('msg')}"
            )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}
