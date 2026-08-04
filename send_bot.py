"""Send one text message to a DingTalk group via robot OpenAPI.

Usage:
  python send_bot.py "hello"
  python send_bot.py group:cidxxxx "hello"
  python send_bot.py cidxxxx "hello"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_IM_APP = _ROOT / "apps" / "im-module"
_IM_SRC = _IM_APP / "src"
if str(_IM_SRC) not in sys.path:
    sys.path.insert(0, str(_IM_SRC))


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(_IM_APP / ".env", override=True)

    args = sys.argv[1:]
    if not args:
        print('usage: python send_bot.py [group_id] "message"', file=sys.stderr)
        return 2

    if len(args) == 1:
        group_id = (os.environ.get("DINGTALK_TEST_CHAT_ID") or "").strip()
        text = args[0]
    else:
        group_id, text = args[0], args[1]

    if not group_id or not text:
        print("missing group_id or message", file=sys.stderr)
        return 2
    if not group_id.startswith("group:") and not group_id.startswith("oto:"):
        group_id = f"group:{group_id}"

    client_id = (
        os.environ.get("DINGTALK_CLIENT_ID", "").strip()
        or os.environ.get("DINGTALK_APP_KEY", "").strip()
    )
    client_secret = (
        os.environ.get("DINGTALK_CLIENT_SECRET", "").strip()
        or os.environ.get("DINGTALK_APP_SECRET", "").strip()
    )
    robot_code = os.environ.get("DINGTALK_ROBOT_CODE", "").strip() or client_id
    if not client_id or not client_secret:
        print("DINGTALK_CLIENT_ID / DINGTALK_CLIENT_SECRET missing", file=sys.stderr)
        return 2

    from channels.dingtalk import DingTalkChannel

    DingTalkChannel(client_id, client_secret, robot_code=robot_code).reply_text(
        group_id, text
    )
    print(f"ok chat_id={group_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
