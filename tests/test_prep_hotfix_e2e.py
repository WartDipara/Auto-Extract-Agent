"""
完整预处理 E2E（不调用 OpenCode）。

流程: 下载 -> 二进制Manifest打debuggable并签名 -> zip解压到decoded/
      -> 安装(小米弹窗) -> 启动 -> OCR门禁 -> 拉热更 -> 关游戏并卸载
通过条件: workspace/<task_key>/hotfix/ 下存在至少一个非空文件

PowerShell 运行示例:

  cd D:\\smwl\\Auto-Extract-Agent
  $env:PYTHONUTF8 = "1"
  # 可选: $env:ADB_SERIAL = "你的设备序列号"
  python .\\tests\\test_prep_hotfix_e2e.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_APP = _REPO / "apps" / "auto-extract"
_SRC = _APP / "src"
for p in (_APP, _SRC, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

TEST_APK_URL = (
    "https://down.x7sy.com/game/android/5/3772/17617_5_1-0-0_20260724203435_3757.apk"
)


def test_prep_hotfix_pull():
    import config
    from prep import run_device_prep
    from prep.hotfix_pull import hotfix_has_content
    from shared.archive_contract import reset_task_workspace

    print("=== PREP E2E START ===", flush=True)
    print(f"URL={TEST_APK_URL}", flush=True)
    task_key = Path(TEST_APK_URL).stem
    task_root = reset_task_workspace(config.WORKSPACE_ROOT, task_key)
    result = run_device_prep(url=TEST_APK_URL, task_root=task_root)
    print(
        "=== PREP E2E RESULT ===\n"
        f"package={result.package_name}\n"
        f"pull_source={result.pull_source}\n"
        f"screen_reached={result.screen_reached}\n"
        f"hotfix_dir={result.hotfix_dir}\n"
        f"hotfix_has_files={result.hotfix_has_files}",
        flush=True,
    )
    assert result.package_name, "package_name empty"
    assert result.hotfix_dir.is_dir(), f"missing hotfix dir: {result.hotfix_dir}"
    assert hotfix_has_content(result.hotfix_dir), (
        f"hotfix has no files after pull_source={result.pull_source} "
        f"screen={result.screen_reached}"
    )
    assert result.hotfix_has_files is True


if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    test_prep_hotfix_pull()
    print("PREP_HOTFIX_E2E_OK", flush=True)
