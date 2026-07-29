"""
用 opencode 非交互方式调用 skill（方法1: --command）。

  cd D:\\smwl\\Auto-Extract-Agent
  $env:PYTHONUTF8 = "1"
  python .\\tests\\test_opencode_skill_run.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SKILL = "get-game-text-skill"
_OUT_TXT = _HERE / "get-game-text-skill_desc.txt"

_PROMPT = (
    f"请用简洁中文描述 skill「{_SKILL}」是做什么的（用途、适用场景、输出要求），"
    f"把完整说明写入本目录文件：{_OUT_TXT.name}。"
    f"只写该 txt，不要改其他文件。"
)


def test_opencode_skill_describe():
    opencode = shutil.which("opencode")
    if not opencode:
        raise FileNotFoundError("opencode not found in PATH")

    if _OUT_TXT.exists():
        _OUT_TXT.unlink()

    cmd = [
        opencode,
        "run",
        "--command",
        _SKILL,
        "--auto",
        "--variant",
        "max",
        "--dir",
        str(_HERE),
        _PROMPT,
    ]
    print("=== OPENCODE SKILL RUN ===", flush=True)
    print(" ".join(cmd), flush=True)
    proc = subprocess.run(
        cmd,
        cwd=str(_HERE),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(f"exit_code={proc.returncode}", flush=True)
    if proc.returncode != 0:
        raise RuntimeError(f"opencode failed with exit {proc.returncode}")

    if not _OUT_TXT.is_file() or _OUT_TXT.stat().st_size <= 0:
        raise AssertionError(f"missing or empty output: {_OUT_TXT}")
    print(f"wrote {_OUT_TXT} ({_OUT_TXT.stat().st_size} bytes)", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    test_opencode_skill_describe()
    print("OPENCODE_SKILL_RUN_OK", flush=True)
