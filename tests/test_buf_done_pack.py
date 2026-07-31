"""Tests for buf_done result CSV zip packing."""

from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "apps" / "auto-extract"
_SRC = _APP / "src"
for p in (_APP, _SRC, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def test_pack_single_csv(tmp_path):
    from buf_done import pack_result_zip

    primary = tmp_path / "demo_纯简.csv"
    primary.write_text("你好\n", encoding="utf-8-sig")
    out = tmp_path / "buf_done"
    zip_path = pack_result_zip(primary, out_dir=out)
    assert zip_path == out / "demo_纯简.zip"
    assert primary.is_file()
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.namelist() == ["demo_纯简.csv"]


def test_pack_dual_csv_includes_t(tmp_path):
    from buf_done import collect_result_csvs, pack_result_zip

    primary = tmp_path / "demo_混用.csv"
    trad = tmp_path / "demo_混用_T.csv"
    primary.write_text("简体\n", encoding="utf-8-sig")
    trad.write_text("繁體\n", encoding="utf-8-sig")
    assert [p.name for p in collect_result_csvs(primary)] == [
        "demo_混用.csv",
        "demo_混用_T.csv",
    ]
    zip_path = pack_result_zip(primary, out_dir=tmp_path / "buf_done")
    with zipfile.ZipFile(zip_path) as zf:
        assert sorted(zf.namelist()) == ["demo_混用.csv", "demo_混用_T.csv"]
    assert primary.is_file() and trad.is_file()


def test_enqueue_does_not_block(tmp_path, monkeypatch):
    import buf_done
    import config

    monkeypatch.setattr(config, "BUF_DONE_DIR", tmp_path / "buf_done")
    # Reset worker so this test owns the queue/thread.
    buf_done._worker_started = False
    primary = tmp_path / "demo_异步.csv"
    primary.write_text("行\n", encoding="utf-8-sig")
    buf_done.enqueue_buf_done(primary)
    zip_path = tmp_path / "buf_done" / "demo_异步.zip"
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not zip_path.is_file():
        time.sleep(0.05)
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.namelist() == ["demo_异步.csv"]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        test_pack_single_csv(p)
        test_pack_dual_csv_includes_t(p)
    print("BUF_DONE_PACK_OK")
