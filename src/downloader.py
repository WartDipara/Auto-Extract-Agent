import logging
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

import config

_log = logging.getLogger(__name__)


def _filename_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if not name:
        name = "download.apk"
    if not name.lower().endswith(".apk"):
        name = f"{name}.apk"
    return name


def download(url: str, dest_dir: Path | None = None) -> Path:
    target_dir = dest_dir or config.DOWNLOADS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = _filename_from_url(url)
    dest = target_dir / filename
    _log.info("downloading %s -> %s", url, dest)
    with requests.get(url, stream=True, timeout=config.DOWNLOAD_TIMEOUT_SEC) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fp:
            for chunk in resp.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    fp.write(chunk)
    return dest
