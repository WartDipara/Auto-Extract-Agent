from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from prep.adb_device import AdbDevice

_log = logging.getLogger(__name__)

_PKG_ACTIVITY_RE = re.compile(r"([a-zA-Z0-9_.]+)/[a-zA-Z0-9_.]+")


def parse_rotation_token(raw: str) -> int | None:
    raw = raw.replace("ROTATION_", "")
    try:
        val = int(raw)
    except ValueError:
        return None
    if val in (0, 1, 2, 3):
        return val * 90
    if val in (0, 90, 180, 270):
        return val
    return None


class DeviceHandler(Protocol):
    name: str

    def match(self, adb: AdbDevice) -> bool: ...

    def install_apk(
        self,
        adb: AdbDevice,
        apk_path: Path,
        *,
        timeout: int = 600,
        package_name: str | None = None,
    ) -> None: ...

    def foreground_package(self, dumpsys: str) -> str: ...

    def screen_rotation(self, dumpsys: str) -> int: ...


class DefaultHandler:
    name = "default"

    def match(self, adb: AdbDevice) -> bool:
        return True

    def install_apk(
        self,
        adb: AdbDevice,
        apk_path: Path,
        *,
        timeout: int = 600,
        package_name: str | None = None,
    ) -> None:
        print(f"adb install {apk_path.name}", flush=True)
        adb.install(apk_path, timeout=timeout)
        print("adb install ok", flush=True)

    def foreground_package(self, dumpsys: str) -> str:
        for line in dumpsys.splitlines():
            if "mCurrentFocus=" not in line and "mFocusedApp=" not in line:
                continue
            match = _PKG_ACTIVITY_RE.search(line)
            if match:
                return match.group(1)
        return ""

    def screen_rotation(self, dumpsys: str) -> int:
        for line in dumpsys.splitlines():
            if "mRotation=" not in line and "mCurrentRotation=" not in line:
                continue
            for token in line.replace(",", " ").split():
                if token.startswith("mRotation="):
                    raw = token.split("=", 1)[1]
                elif token.startswith("mCurrentRotation="):
                    raw = token.split("=", 1)[1]
                else:
                    continue
                rot = parse_rotation_token(raw)
                if rot is not None:
                    return rot
        return 0


HANDLERS: list[DeviceHandler] = []
_DEFAULT = DefaultHandler()


def register(handler: DeviceHandler) -> None:
    HANDLERS.append(handler)
    _log.info("device handler registered: %s", handler.name)


def dispatch(adb: AdbDevice) -> DeviceHandler:
    for handler in HANDLERS:
        if handler.match(adb):
            return handler
    return _DEFAULT
