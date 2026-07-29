import logging
import re
import shutil
import subprocess
from pathlib import Path

import config

_log = logging.getLogger(__name__)

_LABEL_RE = re.compile(
    r"^application-label(?:-([\w-]+))?:'((?:\\'|[^'])*)'\s*$"
)
_WIN_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _resolve_aapt() -> str | None:
    configured = getattr(config, "AAPT_PATH", "") or ""
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("aapt")
    if found:
        return found
    sdk = Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "build-tools"
    if sdk.is_dir():
        versions = sorted(sdk.iterdir(), reverse=True)
        for ver in versions:
            candidate = ver / "aapt.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def extract_labels(apk_path: Path) -> dict:
    aapt = _resolve_aapt()
    if aapt is None:
        _log.error("aapt not found, skip label extract for %s", apk_path.name)
        return {}
    result = subprocess.run(
        [aapt, "dump", "badging", str(apk_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    labels = {}
    for line in result.stdout.splitlines():
        match = _LABEL_RE.match(line.strip())
        if not match:
            continue
        locale = match.group(1) or "default"
        value = match.group(2).replace("\\'", "'")
        labels[locale] = value
    _log.info("labels for %s: %s", apk_path.name, labels)
    return labels


def primary_label(labels: dict) -> str:
    for key in (
        "zh-CN",
        "zh-Hans",
        "zh",
        "zh-TW",
        "zh-HK",
        "zh-Hant",
        "en",
        "en-US",
        "en-GB",
        "default",
    ):
        value = labels.get(key)
        if value:
            return value
    for value in labels.values():
        if value:
            return value
    return ""


def sanitize_label_for_filename(label: str) -> str:
    text = (label or "").strip()
    if not text:
        return "unknown"
    text = _WIN_BAD.sub("_", text)
    text = text.replace(" ", "")
    text = re.sub(r"_+", "_", text).strip("._")
    if len(text) > 80:
        text = text[:80].rstrip("._")
    return text or "unknown"
