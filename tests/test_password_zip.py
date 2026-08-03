"""Local test: pack test_workspace/testzip.csv via buf_done encrypt path."""

from __future__ import annotations

import sys
from pathlib import Path

import pyzipper

_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "apps" / "auto-extract"
_SRC = _APP / "src"
_WORKSPACE = _ROOT / "tests" / "test_workspace"
_CSV = _WORKSPACE / "testzip.csv"


def _ensure_auto_extract_imports() -> None:
    for p in (str(_SRC), str(_APP)):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    cfg = sys.modules.get("config")
    if cfg is not None and "auto-extract" not in (cfg.__file__ or ""):
        for name in ("config", "buf_done", "queue_manager"):
            sys.modules.pop(name, None)


def test_pack_testzip_csv_with_env_password(tmp_path, monkeypatch):
    _ensure_auto_extract_imports()
    import config
    from buf_done import pack_result_zip

    assert _CSV.is_file(), f"missing fixture: {_CSV}"
    assert config.ZIP_PASSWORD, "ZIP_PASSWORD missing in apps/auto-extract/.env"
    password = config.ZIP_PASSWORD.encode("utf-8")

    # Keep source under tmp so fixture file is untouched; copy bytes.
    primary = tmp_path / _CSV.name
    primary.write_bytes(_CSV.read_bytes())
    bin_path = pack_result_zip(primary, out_dir=tmp_path / "buf_done")
    assert bin_path == tmp_path / "buf_done" / "testzip.bin"

    with pyzipper.AESZipFile(bin_path, "r") as zf:
        zf.setpassword(password)
        assert zf.read(_CSV.name) == _CSV.read_bytes()

    with pyzipper.AESZipFile(bin_path, "r") as zf:
        zf.setpassword(b"wrong-password")
        try:
            zf.read(_CSV.name)
            raised = False
        except RuntimeError:
            raised = True
    assert raised, "wrong password should fail to decrypt"


if __name__ == "__main__":
    _ensure_auto_extract_imports()
    import config
    from buf_done import pack_result_zip

    if not config.ZIP_PASSWORD:
        raise SystemExit("ZIP_PASSWORD missing in apps/auto-extract/.env")
    out = pack_result_zip(_CSV, out_dir=_WORKSPACE)
    with pyzipper.AESZipFile(out, "r") as zf:
        zf.setpassword(config.ZIP_PASSWORD.encode("utf-8"))
        raw = zf.read(_CSV.name)
    print(f"PASSWORD_ZIP_OK path={out}")
    print(f"content={raw.decode('utf-8', errors='replace')!r}")
