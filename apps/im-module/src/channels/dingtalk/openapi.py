from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

_log = logging.getLogger(__name__)

_OPENAPI = "https://api.dingtalk.com"
_OAPI = "https://oapi.dingtalk.com"
# Enterprise robot message templates (official msgKey).
MSG_KEY_TEXT = "sampleText"
MSG_KEY_FILE = "sampleFile"
# media/upload type=file limit (DingTalk docs).
_MEDIA_FILE_MAX_BYTES = 20 * 1024 * 1024
# sampleFile fileType values DingTalk documents.
_FILE_TYPE_BY_SUFFIX = {
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".pdf": "pdf",
    ".zip": "zip",
    ".rar": "rar",
    ".doc": "doc",
    ".docx": "docx",
    # Result packs are AES zip saved as .bin — send as zip.
    ".bin": "zip",
}


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
    """Return (dingtalk_file_name, fileType) for sampleFile / media upload."""
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
