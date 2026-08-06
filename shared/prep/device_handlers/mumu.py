from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from errors import TaskError
from ..adb_device import AdbDevice
from ..device_router import DefaultHandler, parse_rotation_token

_log = logging.getLogger(__name__)

_MUMU_SERIAL_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}:\d+$")
_PKG_ACTIVITY_RE = re.compile(r"([a-zA-Z0-9_.]+)/[a-zA-Z0-9_.]+")
_DISPLAY_ID_RE = re.compile(r"Display:\s*mDisplayId=(\d+)")


def parse_mumu_display_focus(dumpsys: str) -> tuple[str, int]:
    """Pick package + rotation of mTopFocusedDisplayId (MuMu multi-window)."""
    top_match = re.search(r"mTopFocusedDisplayId=(\d+)", dumpsys)
    top_id = int(top_match.group(1)) if top_match else None

    displays: dict[int, dict[str, object]] = {}
    current_id: int | None = None
    for line in dumpsys.splitlines():
        disp = _DISPLAY_ID_RE.search(line)
        if disp:
            current_id = int(disp.group(1))
            displays.setdefault(current_id, {"package": "", "rotation": None})
            continue
        if current_id is None:
            continue
        slot = displays[current_id]
        if "mFocusedApp=" in line or "mCurrentFocus=" in line:
            match = _PKG_ACTIVITY_RE.search(line)
            if match:
                slot["package"] = match.group(1)
        if "mCurrentRotation=" in line:
            for token in line.replace(",", " ").split():
                if not token.startswith("mCurrentRotation="):
                    continue
                rot = parse_rotation_token(token.split("=", 1)[1])
                if rot is not None:
                    slot["rotation"] = rot

    if top_id is not None and top_id in displays:
        slot = displays[top_id]
        rot = slot["rotation"]
        return str(slot["package"] or ""), int(rot if rot is not None else 0)

    for slot in reversed(list(displays.values())):
        if slot["package"]:
            rot = slot["rotation"]
            return str(slot["package"]), int(rot if rot is not None else 0)
    return "", 0


class MuMuHandler(DefaultHandler):
    name = "mumu"

    def match(self, adb: AdbDevice) -> bool:
        return bool(_MUMU_SERIAL_RE.match(adb.serial or ""))

    def install_apk(
        self,
        adb: AdbDevice,
        apk_path: Path,
        *,
        timeout: int = 600,
        package_name: str | None = None,
    ) -> None:
        print("install monitor skip (mumu poll package)", flush=True)
        _log.info("mumu install poll serial=%s package=%s", adb.serial, package_name or "")
        print(f"adb install {apk_path.name}", flush=True)
        adb.install(apk_path, timeout=timeout)
        if not package_name:
            print("adb install ok", flush=True)
            return

        deadline = time.monotonic() + min(60.0, float(timeout))
        while time.monotonic() < deadline:
            if adb.is_package_installed(package_name):
                print("adb install ok", flush=True)
                _log.info("mumu package installed %s", package_name)
                return
            time.sleep(1.0)
        raise TaskError(
            code="PREP_INSTALL",
            message=f"mumu install timeout waiting for package {package_name}",
            details={"package": package_name, "serial": adb.serial or ""},
        )

    def foreground_package(self, dumpsys: str) -> str:
        pkg, _ = parse_mumu_display_focus(dumpsys)
        return pkg

    def screen_rotation(self, dumpsys: str) -> int:
        _, rot = parse_mumu_display_focus(dumpsys)
        return rot
