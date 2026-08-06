from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

import config

_log = logging.getLogger(__name__)
_LOCKS_GUARD = threading.Lock()
_FILE_LOCKS: dict[str, threading.Lock] = {}
_UNLINK_RETRIES = 5
_UNLINK_SLEEP_SEC = 0.2


def _filename_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if not name:
        name = "download.apk"
    if not name.lower().endswith(".apk"):
        name = f"{name}.apk"
    return name


def _lock_for(filename: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _FILE_LOCKS.get(filename)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[filename] = lock
        return lock


def _unlink_retry(path: Path) -> None:
    if not path.exists():
        return
    last: Exception | None = None
    for _ in range(_UNLINK_RETRIES):
        try:
            path.unlink()
            return
        except OSError as exc:
            last = exc
            # WinError 32: file in use — wait briefly.
            time.sleep(_UNLINK_SLEEP_SEC)
    if last is not None:
        raise last


def _replace_retry(src: Path, dest: Path) -> None:
    last: Exception | None = None
    for _ in range(_UNLINK_RETRIES):
        try:
            src.replace(dest)
            return
        except OSError as exc:
            last = exc
            time.sleep(_UNLINK_SLEEP_SEC)
    if last is not None:
        raise last


def download(url: str, dest_dir: Path | None = None) -> Path:
    """Download URL into downloads dir. Same filename is serialized (Windows-safe)."""
    target_dir = dest_dir or config.DOWNLOADS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = _filename_from_url(url)
    dest = (target_dir / filename).resolve()
    with _lock_for(filename):
        # Another worker may have just finished the same APK.
        if dest.is_file() and dest.stat().st_size > 0:
            _log.info("download reuse existing %s (%s bytes)", dest.name, dest.stat().st_size)
            return dest
        part = target_dir / f".{filename}.{uuid.uuid4().hex}.part"
        print(f"downloading {filename}", flush=True)
        _log.info("downloading %s -> %s", url, dest)
        try:
            with requests.get(
                url, stream=True, timeout=config.DOWNLOAD_TIMEOUT_SEC
            ) as resp:
                resp.raise_for_status()
                with part.open("wb") as fp:
                    for chunk in resp.iter_content(
                        chunk_size=config.DOWNLOAD_CHUNK_SIZE
                    ):
                        if chunk:
                            fp.write(chunk)
            if dest.is_file():
                _unlink_retry(dest)
            _replace_retry(part, dest)
        finally:
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    _log.warning("leftover partial download: %s", part)
        print(f"download finished {filename}", flush=True)
        return dest
