"""
独立调用 OpenCode：对 test_workspace/libcocos2dlua.so 做 aries-wow-sign xref 分析。

会话管理：一任务一会话（续聊用 -s）；新任务新开会话；session 写入 state/opencode_sessions.jsonl。
落盘校验：产物缺失则在同一会话内催写，最多 N 次。

  cd D:\\smwl\\Auto-Extract-Agent\\apps\\auto-extract
  $env:PYTHONUTF8 = "1"
  python .\\tests\\test_opencode_aries_xref.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from opencode_session import OpenCodeSessionManager  # noqa: E402

_WS = _HERE / "test_workspace"
_SO = _WS / "libcocos2dlua.so"
_OUT = _WS / "aries_wow_sign_xref_report.txt"

_SKILL = "idapromcp-skill"
_MAX_NUDGE = 2
# 每次跑脚本视为一个新任务（新 session）；同一次脚本内的催写续同一 session
_TASK_KEY = f"aries-xref-{int(time.time())}"

_PROMPT = f"""
你是逆向分析任务，必须独立完成，禁止向用户提问或等待确认。

【目标】
分析字符串 `aries-wow-sign` 的 xref（交叉引用），弄清它和哪段解密逻辑有关
（例如 setXXTEAKeyAndSign / xxtea_decrypt / LuaStack::init 等）。

【落盘硬性要求 — 违反即任务失败】
1. 必须调用 Write（或等价写文件工具）创建真实文件：
   {_OUT.resolve()}
2. 禁止只把结论写在对话回复里；对话里写了不算完成。
3. 不论分析成功还是失败，都必须落盘：
   - 成功：完整结论报告
   - 失败：写明失败原因与已尝试步骤
4. 写完文件后再结束；未写文件前不得声称「已完成」。

【输入】
SO 绝对路径：{_SO.resolve()}
工作目录：{_WS.resolve()}

【分析约束】
1. 必须用 IDA Pro MCP（idalib-mcp）分析本 SO，禁止 capstone/objdump/ghidra。
2. 先 idb_open 打开上述 SO（run_auto_analysis=false 快速加载），再用 find_regex / xrefs_to
   定位 `aries-wow-sign`，反编译/反汇编相关函数，追到解密调用链。
3. 凡编写或执行 Python/脚本，必须在 conda 环境 `agent-ida` 中运行，例如：
   `conda run -n agent-ida python ...`
   禁止用系统默认 python。
4. 报告用简洁中文，至少包含：aries-wow-sign 所在地址、xref 到哪些函数、
   与解密逻辑的关系、关键汇编/反编译摘录、结论是否为 XXTEA/Aries 类。
5. 只写报告 txt 与必要临时脚本（放在 {_WS.resolve()}），不要改仓库其他代码。
""".strip()

_NUDGE_PROMPT = f"""
校验失败：约定输出文件不存在或为空：
{_OUT.resolve()}

你上次只在对话里输出了结论，没有调用写文件工具。这视为未完成。

现在立刻用 Write 工具把结论写入上述绝对路径（覆盖或新建均可）。
- 若分析已有结论：把完整结论写入该 txt
- 若分析失败：写入失败原因与已尝试步骤
不论成败都必须落盘。写完文件后再结束；禁止仅回复文字。
""".strip()


def _report_ok() -> bool:
    return _OUT.is_file() and _OUT.stat().st_size > 0


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not _SO.is_file():
        raise FileNotFoundError(_SO)

    _WS.mkdir(parents=True, exist_ok=True)
    if _OUT.exists():
        _OUT.unlink()

    mgr = OpenCodeSessionManager()
    print(f"task_key={_TASK_KEY}", flush=True)

    result = mgr.run(
        task_key=_TASK_KEY,
        prompt=_PROMPT,
        cwd=_WS,
        skill=_SKILL,
        force_new=True,
        print_live=True,
    )
    print(
        f"initial done session={result.session_id or '-'} exit={result.returncode}",
        flush=True,
    )

    if _report_ok():
        print(f"report ok: {_OUT} ({_OUT.stat().st_size} bytes)", flush=True)
        print("OPENCODE_ARIES_XREF_OK", flush=True)
        return

    print("report missing; nudge in SAME session...", flush=True)
    for i in range(1, _MAX_NUDGE + 1):
        if not mgr.lookup_session_id(_TASK_KEY):
            raise RuntimeError("no session_id bound; cannot continue same session")
        nudge = mgr.run(
            task_key=_TASK_KEY,
            prompt=_NUDGE_PROMPT,
            cwd=_WS,
            skill=None,
            force_new=False,
            print_live=True,
        )
        print(
            f"nudge {i}/{_MAX_NUDGE} session={nudge.session_id} exit={nudge.returncode}",
            flush=True,
        )
        if _report_ok():
            print(f"report ok after nudge: {_OUT} ({_OUT.stat().st_size} bytes)", flush=True)
            print("OPENCODE_ARIES_XREF_OK", flush=True)
            return

    raise AssertionError(
        f"missing report after initial + {_MAX_NUDGE} nudges: {_OUT} "
        f"session={mgr.lookup_session_id(_TASK_KEY)}"
    )


if __name__ == "__main__":
    main()
