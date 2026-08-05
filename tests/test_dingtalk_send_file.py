"""Unit tests for DingTalk OpenAPI file send helpers (no live network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_IM_SRC = _ROOT / "apps" / "im-module" / "src"
if str(_IM_SRC) not in sys.path:
    sys.path.insert(0, str(_IM_SRC))


def test_resolve_send_file_meta_bin_as_zip():
    from channels.dingtalk.openapi import resolve_send_file_meta

    name, ftype = resolve_send_file_meta(Path("魔力宝贝：启程.bin"))
    assert name == "魔力宝贝：启程.zip"
    assert ftype == "zip"


def test_resolve_send_file_meta_xlsx():
    from channels.dingtalk.openapi import resolve_send_file_meta

    name, ftype = resolve_send_file_meta(Path("export.xlsx"))
    assert name == "export.xlsx"
    assert ftype == "xlsx"


def test_resolve_send_file_meta_rejects_unknown(tmp_path: Path):
    from channels.dingtalk.openapi import resolve_send_file_meta

    with pytest.raises(RuntimeError, match="cannot send file type"):
        resolve_send_file_meta(tmp_path / "note.txt")


def test_upload_and_send_group_file(tmp_path: Path):
    from channels.dingtalk.openapi import DingTalkOpenApi

    path = tmp_path / "result.bin"
    path.write_bytes(b"PK\x03\x04fake-zip")

    api = DingTalkOpenApi("app", "secret", "robot")
    api._token = "tok"
    api._token_expire_at = 1e18

    upload_resp = MagicMock()
    upload_resp.status_code = 200
    upload_resp.text = '{"errcode":0,"media_id":"@media123"}'
    upload_resp.json.return_value = {"errcode": 0, "media_id": "@media123"}

    send_resp = MagicMock()
    send_resp.status_code = 200
    send_resp.text = '{"processQueryKey":"pqk"}'
    send_resp.json.return_value = {"processQueryKey": "pqk"}

    with patch("channels.dingtalk.openapi.requests.post") as post:
        post.side_effect = [upload_resp, send_resp]
        media_id = api.upload_media(path)
        assert media_id == "@media123"
        out = api.send_group_file(
            "cidABC",
            media_id=media_id,
            file_name="result.zip",
            file_type="zip",
        )
        assert out["processQueryKey"] == "pqk"

    assert post.call_count == 2
    upload_call, send_call = post.call_args_list
    assert "media/upload" in upload_call.args[0]
    assert upload_call.kwargs["params"]["type"] == "file"
    # upload uses original bytes under a .zip filename
    media_tuple = upload_call.kwargs["files"]["media"]
    assert media_tuple[0] == "result.zip"

    body = send_call.kwargs["json"]
    assert body["msgKey"] == "sampleFile"
    param = json.loads(body["msgParam"])
    assert param == {
        "mediaId": "@media123",
        "fileName": "result.zip",
        "fileType": "zip",
    }


def test_channel_send_file_group(tmp_path: Path):
    from channels.dingtalk.channel import DingTalkChannel

    path = tmp_path / "a.bin"
    path.write_bytes(b"data")
    ch = DingTalkChannel("id", "secret", robot_code="robot")
    ch._api = MagicMock()
    ch._api.upload_media.return_value = "@m1"
    ch.send_file("group:cid1", path)
    ch._api.upload_media.assert_called_once()
    ch._api.send_group_file.assert_called_once_with(
        "cid1",
        media_id="@m1",
        file_name="a.zip",
        file_type="zip",
    )
