"""
DingTalk live robot tests (Stream receive + OpenAPI send).

NOT run in normal CI. Requires real credentials in apps/im-module/.env.

Usage (PowerShell):

  cd D:\\smwl\\Auto-Extract-Agent
  $env:PYTHONUTF8 = "1"
  $env:DINGTALK_LIVE = "1"
  # optional — proactive send target (print after first @ receive):
  # $env:DINGTALK_TEST_CHAT_ID = "group:cidxxxxxxxx"
  python .\\tests\\test_dingtalk_live.py

Or:

  $env:DINGTALK_LIVE = "1"
  pytest -q .\\tests\\test_dingtalk_live.py -s

Flow for receive/reply:
  1) script starts Stream
  2) in DingTalk group (or 1:1), @robot and send: 钉钉联调
  3) bot waits 5s then replies: 测试成功
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_IM_APP = _ROOT / "apps" / "im-module"
_IM_SRC = _IM_APP / "src"
for p in (_IM_SRC, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

TRIGGER = "钉钉联调"
REPLY_OK = "测试成功"
SEND_PROBE = "【测试】钉钉机器人主动发送"
DEFAULT_WAIT_SEC = 120.0
DELAY_REPLY_SEC = 5.0


def _load_env() -> None:
    from dotenv import load_dotenv

    # Prefer im-module/.env; override so trailing IM_CHANNEL=dingtalk wins.
    load_dotenv(_IM_APP / ".env", override=True)


def _live_enabled() -> bool:
    return (os.environ.get("DINGTALK_LIVE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _creds() -> tuple[str, str, str]:
    client_id = (
        os.environ.get("DINGTALK_CLIENT_ID", "").strip()
        or os.environ.get("DINGTALK_APP_KEY", "").strip()
    )
    client_secret = (
        os.environ.get("DINGTALK_CLIENT_SECRET", "").strip()
        or os.environ.get("DINGTALK_APP_SECRET", "").strip()
    )
    robot_code = (
        os.environ.get("DINGTALK_ROBOT_CODE", "").strip() or client_id
    )
    return client_id, client_secret, robot_code


def _require_live():
    import pytest

    if not _live_enabled():
        pytest.skip("set DINGTALK_LIVE=1 to run DingTalk live tests")
    _load_env()
    client_id, client_secret, _robot = _creds()
    if not client_id or not client_secret:
        pytest.skip("DINGTALK_CLIENT_ID / DINGTALK_CLIENT_SECRET missing in .env")


def _wait_sec() -> float:
    raw = (os.environ.get("DINGTALK_LIVE_TIMEOUT_SEC") or "").strip()
    if not raw:
        return DEFAULT_WAIT_SEC
    return max(10.0, float(raw))


def test_dingtalk_access_token():
    """OpenAPI: exchange Client ID/Secret for accessToken."""
    _require_live()
    from channels.dingtalk.openapi import DingTalkOpenApi

    client_id, client_secret, robot_code = _creds()
    api = DingTalkOpenApi(client_id, client_secret, robot_code)
    token = api.access_token()
    assert token and isinstance(token, str)
    print(f"DINGTALK_TOKEN_OK len={len(token)}", flush=True)


def test_dingtalk_send_specific_message():
    """OpenAPI: send a fixed probe text to DINGTALK_TEST_CHAT_ID."""
    _require_live()
    chat_id = (os.environ.get("DINGTALK_TEST_CHAT_ID") or "").strip()
    if not chat_id:
        import pytest

        pytest.skip(
            "set DINGTALK_TEST_CHAT_ID=group:<openConversationId> "
            "or oto:<staffId> (printed by receive test)"
        )

    from channels.dingtalk import DingTalkChannel

    client_id, client_secret, robot_code = _creds()
    channel = DingTalkChannel(client_id, client_secret, robot_code=robot_code)
    channel.reply_text(chat_id, SEND_PROBE)
    print(f"DINGTALK_SEND_OK chat_id={chat_id} text={SEND_PROBE!r}", flush=True)


def test_dingtalk_receive_and_delayed_reply():
    """
    Stream: wait for @bot message containing TRIGGER, sleep 5s, reply REPLY_OK.

    Manual step required: @ the robot in DingTalk and send the trigger text.
    """
    _require_live()
    from channels.dingtalk import DingTalkChannel

    client_id, client_secret, robot_code = _creds()
    channel = DingTalkChannel(client_id, client_secret, robot_code=robot_code)

    done = threading.Event()
    errors: list[BaseException] = []
    received: dict[str, str] = {}

    def on_message(chat_id: str, text: str) -> None:
        print(f"[stream] chat_id={chat_id} text={text!r}", flush=True)
        if TRIGGER not in text:
            print(
                f"[stream] ignore (need substring {TRIGGER!r})",
                flush=True,
            )
            return
        if done.is_set() or received:
            return
        received["chat_id"] = chat_id
        received["text"] = text

        def _delayed_reply() -> None:
            try:
                print(
                    f"[reply] waiting {DELAY_REPLY_SEC:.0f}s then send {REPLY_OK!r}",
                    flush=True,
                )
                time.sleep(DELAY_REPLY_SEC)
                channel.reply_text(chat_id, REPLY_OK)
                print(
                    f"[reply] sent ok; export DINGTALK_TEST_CHAT_ID={chat_id}",
                    flush=True,
                )
                done.set()
            except BaseException as exc:  # noqa: BLE001 — surface in test thread
                errors.append(exc)
                done.set()

        threading.Thread(target=_delayed_reply, name="ding-reply", daemon=True).start()

    stream = threading.Thread(
        target=channel.start,
        args=(on_message,),
        name="ding-stream",
        daemon=True,
    )
    stream.start()
    timeout = _wait_sec()
    print(
        (
            f"\n=== DingTalk live receive ===\n"
            f"Stream started (client_id={client_id}).\n"
            f"In DingTalk, @ the robot and send exactly (or containing):\n"
            f"  {TRIGGER}\n"
            f"Expect reply after {DELAY_REPLY_SEC:.0f}s: {REPLY_OK}\n"
            f"Waiting up to {timeout:.0f}s ...\n"
        ),
        flush=True,
    )
    ok = done.wait(timeout=timeout)
    assert ok, (
        f"timeout waiting for @{TRIGGER!r}; "
        "check Stream mode, bot in group, and @ mention"
    )
    if errors:
        raise errors[0]
    assert received.get("chat_id")
    assert TRIGGER in received.get("text", "")
    print(
        f"DINGTALK_RECEIVE_REPLY_OK chat_id={received['chat_id']}",
        flush=True,
    )


def main() -> int:
    _load_env()
    os.environ.setdefault("DINGTALK_LIVE", "1")
    if not _live_enabled():
        print("set DINGTALK_LIVE=1", flush=True)
        return 2
    client_id, client_secret, _ = _creds()
    if not client_id or not client_secret:
        print("missing DINGTALK_CLIENT_ID / DINGTALK_CLIENT_SECRET", flush=True)
        return 2

    print("--- 1/3 access_token ---", flush=True)
    test_dingtalk_access_token()

    chat_id = (os.environ.get("DINGTALK_TEST_CHAT_ID") or "").strip()
    if chat_id:
        print("--- 2/3 send_specific_message ---", flush=True)
        test_dingtalk_send_specific_message()
    else:
        print(
            "--- 2/3 send skipped (no DINGTALK_TEST_CHAT_ID) ---",
            flush=True,
        )

    print("--- 3/3 receive_and_delayed_reply ---", flush=True)
    test_dingtalk_receive_and_delayed_reply()
    print("ALL_DINGTALK_LIVE_OK", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
