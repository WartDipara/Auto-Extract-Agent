from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import requests

_log = logging.getLogger(__name__)

_OPENAPI = "https://api.dingtalk.com"
_OAPI = "https://oapi.dingtalk.com"
MSG_KEY_TEXT = "sampleText"
MSG_KEY_FILE = "sampleFile"
_MEDIA_FILE_MAX_BYTES = 20 * 1024 * 1024
_FILE_TYPE_BY_SUFFIX = {
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".pdf": "pdf",
    ".zip": "zip",
    ".rar": "rar",
    ".doc": "doc",
    ".docx": "docx",
    ".bin": "zip",
}


@dataclass(frozen=True)
class SessionReplyTarget:
    webhook: str
    expire_at_ms: int
    sender_staff_id: str = ""
    sender_nick: str = ""

    def alive(self, *, now_ms: int | None = None) -> bool:
        current = int(time.time() * 1000) if now_ms is None else now_ms
        return bool(self.webhook) and current < self.expire_at_ms - 5_000


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

    def reply_session_text(
        self,
        target: SessionReplyTarget,
        text: str,
        *,
        at_user_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Reply via sessionWebhook (official stream SDK pattern; supports @)."""
        if not target.alive():
            raise RuntimeError("dingtalk sessionWebhook expired")
        user_ids = [u for u in (at_user_ids or ()) if (u or "").strip()]
        body: dict[str, Any] = {
            "msgtype": "text",
            "text": {"content": text},
        }
        if user_ids:
            body["at"] = {"atUserIds": user_ids, "isAtAll": False}
        resp = requests.post(
            target.webhook,
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            timeout=30,
        )
        if resp.status_code >= 400:
            _log.error(
                "dingtalk sessionWebhook failed status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            resp.raise_for_status()
        data = resp.json() if resp.text else {}
        _log.info(
            "dingtalk sessionWebhook ok at=%s keys=%s",
            user_ids or "-",
            list(data.keys()) if isinstance(data, dict) else type(data).__name__,
        )
        return data if isinstance(data, dict) else {"raw": data}

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

    def send_group_file(
        self,
        open_conversation_id: str,
        *,
        media_id: str,
        file_name: str,
        file_type: str,
    ) -> dict[str, Any]:
        return self._post_robot(
            "/v1.0/robot/groupMessages/send",
            {
                "robotCode": self._robot_code,
                "openConversationId": open_conversation_id,
                "msgKey": MSG_KEY_FILE,
                "msgParam": json.dumps(
                    {
                        "mediaId": media_id,
                        "fileName": file_name,
                        "fileType": file_type,
                    },
                    ensure_ascii=False,
                ),
            },
        )

    def send_oto_file(
        self,
        user_id: str,
        *,
        media_id: str,
        file_name: str,
        file_type: str,
    ) -> dict[str, Any]:
        return self._post_robot(
            "/v1.0/robot/oToMessages/batchSend",
            {
                "robotCode": self._robot_code,
                "userIds": [user_id],
                "msgKey": MSG_KEY_FILE,
                "msgParam": json.dumps(
                    {
                        "mediaId": media_id,
                        "fileName": file_name,
                        "fileType": file_type,
                    },
                    ensure_ascii=False,
                ),
            },
        )

    def upload_media(self, path: Path, *, media_type: str = "file") -> str:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        size = path.stat().st_size
        if media_type == "file" and size > _MEDIA_FILE_MAX_BYTES:
            raise RuntimeError(
                f"dingtalk media upload over {_MEDIA_FILE_MAX_BYTES} bytes: "
                f"{path.name} ({size})"
            )
        upload_name, _file_type = resolve_send_file_meta(path)
        token = self.access_token()
        with path.open("rb") as fp:
            resp = requests.post(
                f"{_OAPI}/media/upload",
                params={"access_token": token, "type": media_type},
                files={"media": (upload_name, fp)},
                timeout=120,
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError(
                f"dingtalk media/upload bad response status={resp.status_code} "
                f"body={resp.text[:300]}"
            ) from exc
        errcode = int(data.get("errcode") or 0)
        if resp.status_code >= 400 or errcode != 0:
            _log.error(
                "dingtalk media/upload failed status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            raise RuntimeError(
                f"dingtalk media/upload failed errcode={errcode} "
                f"errmsg={data.get('errmsg') or resp.text[:200]}"
            )
        media_id = data.get("media_id") or ""
        if not media_id:
            raise RuntimeError(f"dingtalk media/upload empty media_id: {data}")
        _log.info(
            "dingtalk media/upload ok name=%s media_id=%s…",
            upload_name,
            media_id[:16],
        )
        return media_id

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


def resolve_send_file_meta(path: Path) -> tuple[str, str]:
    path = Path(path)
    suffix = path.suffix.lower()
    file_type = _FILE_TYPE_BY_SUFFIX.get(suffix)
    if not file_type:
        supported = ", ".join(sorted(_FILE_TYPE_BY_SUFFIX))
        raise RuntimeError(
            f"dingtalk cannot send file type {suffix or '(none)'}; "
            f"supported: {supported}"
        )
    name = path.name
    if suffix == ".bin":
        name = f"{path.stem}.zip"
    return name, file_type
