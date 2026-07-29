from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path

import config

_log = logging.getLogger(__name__)


class AdbDevice:
    def __init__(self, serial: str | None = None):
        self.serial = serial or ""
        self.adb = config.ADB_CMD

    def _base(self) -> list[str]:
        cmd = [self.adb]
        if self.serial:
            cmd.extend(["-s", self.serial])
        return cmd

    def run(self, args: list[str], timeout: int = 120) -> str:
        cmd = self._base() + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"adb failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr or result.stdout}"
            )
        return (result.stdout or "").strip()

    def shell(self, cmdline: str, timeout: int = 120) -> str:
        return self.run(["shell", cmdline], timeout=timeout)

    def require_one_device(self) -> str:
        out = subprocess.run(
            [self.adb, "devices"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        lines = [
            ln.strip()
            for ln in (out.stdout or "").splitlines()
            if ln.strip() and not ln.startswith("List")
        ]
        devices = []
        for ln in lines:
            parts = ln.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        if self.serial:
            if self.serial not in devices:
                raise RuntimeError(f"ADB_SERIAL={self.serial} not online; online={devices}")
            return self.serial
        if not devices:
            raise RuntimeError("no adb device online")
        if len(devices) > 1:
            raise RuntimeError(
                f"multiple adb devices {devices}; set ADB_SERIAL to pick one"
            )
        self.serial = devices[0]
        _log.info("using adb device %s", self.serial)
        return self.serial

    def brand(self) -> str:
        try:
            return self.shell("getprop ro.product.brand").lower()
        except Exception:
            return ""

    def is_package_installed(self, package: str) -> bool:
        try:
            out = self.shell(f"pm path {package}", timeout=30)
        except RuntimeError:
            return False
        return bool(out.strip()) and "package:" in out

    def uninstall(self, package: str) -> bool:
        """Uninstall package. Returns True if uninstall command reported success."""
        cmd = self._base() + ["uninstall", package]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        ok = result.returncode == 0 and "Success" in (result.stdout or "")
        _log.info(
            "uninstall %s -> rc=%s out=%s",
            package,
            result.returncode,
            (result.stdout or result.stderr or "").strip()[:200],
        )
        return ok

    def ensure_uninstalled(self, package: str) -> bool:
        """If package is installed on device, uninstall it. Returns True if it was installed."""
        if not self.is_package_installed(package):
            _log.info("package not installed: %s", package)
            return False
        _log.info("package installed, uninstalling: %s", package)
        self.uninstall(package)
        # confirm gone (best-effort)
        if self.is_package_installed(package):
            _log.warning("package still present after uninstall: %s", package)
        return True

    def install(self, apk_path: Path, timeout: int = 600):
        self.run(["install", "-r", "-t", "-g", str(apk_path)], timeout=timeout)
        _log.info("installed %s", apk_path)

    def launch_package(self, package: str):
        # Prefer monkey; fallback am
        try:
            self.shell(
                f"monkey -p {package} -c android.intent.category.LAUNCHER 1",
                timeout=60,
            )
        except RuntimeError:
            self.shell(
                f"monkey -p {package} 1",
                timeout=60,
            )
        time.sleep(1.0)
        _log.info("launched %s", package)

    def force_stop(self, package: str):
        try:
            self.shell(f"am force-stop {package}")
            _log.info("force-stop %s", package)
        except RuntimeError as exc:
            _log.warning("force-stop failed: %s", exc)

    def screencap(self, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        remote = "/sdcard/__aea_prep_cap.png"
        self.shell(f"screencap -p {remote}")
        self.run(["pull", remote, str(dest)], timeout=60)
        try:
            self.shell(f"rm {remote}")
        except RuntimeError:
            pass

    def tap(self, x: int, y: int):
        self.shell(f"input tap {int(x)} {int(y)}")

    def wm_size(self) -> tuple[int, int]:
        out = self.shell("wm size")
        match = re.search(r"(\d+)x(\d+)", out)
        if not match:
            return 1080, 2400
        return int(match.group(1)), int(match.group(2))

    def get_screen_rotation(self) -> int:
        """Return rotation in degrees: 0, 90, 180, 270."""
        try:
            out = self.shell("dumpsys window", timeout=15)
        except RuntimeError:
            return 0
        for line in out.splitlines():
            if "mRotation=" not in line and "mCurrentRotation=" not in line:
                continue
            for token in line.replace(",", " ").split():
                key = None
                if token.startswith("mRotation="):
                    key = "mRotation="
                elif token.startswith("mCurrentRotation="):
                    key = "mCurrentRotation="
                if not key:
                    continue
                raw = token.split("=", 1)[1].replace("ROTATION_", "")
                try:
                    val = int(raw)
                except ValueError:
                    continue
                # Surface.ROTATION_* enum 0..3 or degrees
                if val in (0, 1, 2, 3):
                    return val * 90
                if val in (0, 90, 180, 270):
                    return val
        return 0

    def touch_size(self) -> tuple[int, int]:
        """Effective adb input tap space for current orientation."""
        w, h = self.wm_size()
        rot = self.get_screen_rotation()
        if rot in (90, 270):
            w, h = h, w
        return w, h
