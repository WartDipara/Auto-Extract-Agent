"""
OpenCode 冒烟：发一句简单消息，再用 export_session_json 导出对话。

  cd D:\\smwl\\Auto-Extract-Agent
  $env:PYTHONUTF8 = "1"
  $env:PYTHONPATH = "apps/auto-extract/src;."
  python .\\tests\\test_opencode_export.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_APP = _REPO / "apps" / "auto-extract"
_SRC = _APP / "src"
for p in (_SRC, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from opencode_session import OpenCodeSessionManager, export_session_json  # noqa: E402
from shared.archive_contract import OPENCODE_EXPORT_NAME  # noqa: E402

_TASK_KEY = f"export-ping-{int(time.time())}"
_CWD = _HERE / "export_workspace"
_EXPORT_JSON = _CWD / "outputs" / OPENCODE_EXPORT_NAME
_PROMPT = "这是一句冒烟测试。请只回复一个词：pong。不要调用任何工具，不要改文件。"


def test_opencode_ping_and_export():
    _CWD.mkdir(parents=True, exist_ok=True)
    mgr = OpenCodeSessionManager()
    print("=== OPENCODE PING RUN ===", flush=True)
    result = mgr.run(
        task_key=_TASK_KEY,
        prompt=_PROMPT,
        cwd=_CWD,
        skill=None,
        auto=True,
        force_new=True,
        print_live=True,
    )
    print(
        f"run exit={result.returncode} session={result.session_id or '-'}",
        flush=True,
    )
    if not result.session_id:
        raise AssertionError("missing session_id from opencode run")
    if result.returncode != 0:
        raise RuntimeError(f"opencode run failed exit={result.returncode}")

    out = export_session_json(result.session_id, cwd=_CWD, out_path=_EXPORT_JSON)
    data = json.loads(out.read_text(encoding="utf-8"))
    info = data.get("info") or {}
    messages = data.get("messages") or []
    print(
        f"export ok path={out} session={info.get('id') or result.session_id} "
        f"messages={len(messages)} bytes={out.stat().st_size}",
        flush=True,
    )
    if not messages:
        raise AssertionError("exported JSON has no messages")
    print("OPENCODE_EXPORT_OK", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    test_opencode_ping_and_export()
