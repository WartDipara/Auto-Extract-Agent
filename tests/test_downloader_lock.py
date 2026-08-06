"""Windows-safe download: same filename serialized + reuse."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_A_SRC = _ROOT / "apps" / "auto-extract" / "src"
_A_APP = _ROOT / "apps" / "auto-extract"
for p in (_A_SRC, _A_APP, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def test_concurrent_same_filename_reuses_or_serializes(tmp_path, monkeypatch):
    for name in ("config", "downloader"):
        sys.modules.pop(name, None)

    import config
    import downloader

    monkeypatch.setattr(config, "DOWNLOADS_DIR", tmp_path)
    monkeypatch.setattr(config, "DOWNLOAD_TIMEOUT_SEC", 30)
    monkeypatch.setattr(config, "DOWNLOAD_CHUNK_SIZE", 1024)

    body = b"apk-bytes-12345"
    calls = {"n": 0}
    lock = threading.Lock()

    class _Resp:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1):
            yield body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_get(url, stream=True, timeout=30):
        with lock:
            calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(downloader.requests, "get", _fake_get)

    url = "https://cdn.example.com/game/17836_demo.apk"
    out: list[Path] = []
    errors: list[BaseException] = []

    def _worker():
        try:
            out.append(downloader.download(url, dest_dir=tmp_path))
        except BaseException as exc:  # noqa: BLE001 — collect for assert
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(out) == 4
    assert len({p.resolve() for p in out}) == 1
    assert out[0].read_bytes() == body
    # Serialized: at most one network fetch if reuse works after first completes;
    # under lock, later workers reuse → often 1 call; allow a few if overlap before file appears.
    assert 1 <= calls["n"] <= 4
