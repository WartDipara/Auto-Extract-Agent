from __future__ import annotations

import logging
import re
import tempfile
import threading
from pathlib import Path

import uiautomator2 as u2
from ..adb_device import AdbDevice
from ..device_router import DefaultHandler
from ..ocr_util import find_tap_for_texts, ocr_image
from ..screen_coord import resolve_screen_coord_space

_log = logging.getLogger(__name__)

_INSTALL_TEXTS = (
    "继续安装",
    "繼續安裝",
    "安装",
    "安裝",
    "Install",
    "INSTALL",
    "install",
)
_XIAOMI_RE = re.compile(r"xiaomi|redmi|poco")


class XiaomiHandler(DefaultHandler):
    name = "xiaomi"

    def match(self, adb: AdbDevice) -> bool:
        brand = adb.brand()
        manufacturer = ""
        try:
            manufacturer = adb.shell("getprop ro.product.manufacturer").lower()
        except Exception:
            pass
        return bool(_XIAOMI_RE.search(brand) or _XIAOMI_RE.search(manufacturer))

    def install_apk(
        self,
        adb: AdbDevice,
        apk_path: Path,
        *,
        timeout: int = 600,
        package_name: str | None = None,
    ) -> None:
        print("install monitor on (xiaomi dialog)", flush=True)
        shot_dir = Path(tempfile.mkdtemp(prefix="install_mon_"))
        stop = threading.Event()
        thread = threading.Thread(
            target=_monitor_loop,
            args=(adb, stop, shot_dir),
            name="xiaomi-install-monitor",
            daemon=True,
        )
        thread.start()
        _log.info("xiaomi install monitor started brand=%s", adb.brand())
        try:
            print(f"adb install {apk_path.name}", flush=True)
            adb.install(apk_path, timeout=timeout)
            print("adb install ok", flush=True)
        finally:
            stop.set()
            thread.join(timeout=10)


def _monitor_loop(adb: AdbDevice, stop: threading.Event, shot_dir: Path):
    try:
        d = u2.connect(adb.serial) if adb.serial else u2.connect()
        use_u2 = True
    except Exception as exc:
        _log.warning("u2 unavailable for install monitor: %s", exc)
        d = None
        use_u2 = False

    polls = 0
    while not stop.is_set():
        polls += 1
        clicked = False
        if use_u2 and d is not None:
            for text in _INSTALL_TEXTS:
                try:
                    btn = d(text=text)
                    if btn.exists(timeout=0.2):
                        btn.click()
                        _log.info("install monitor u2 click %r", text)
                        clicked = True
                        break
                except Exception:
                    pass
        if not clicked and (not use_u2 or polls % 5 == 0):
            shot = shot_dir / f"install_{polls}.png"
            try:
                adb.screencap(shot)
                space = resolve_screen_coord_space(adb, shot)
                items = ocr_image(shot, device_w=space.tap_w, device_h=space.tap_h)
                pt = find_tap_for_texts(items, _INSTALL_TEXTS)
                if pt:
                    adb.tap(*pt)
                    _log.info("install monitor ocr tap %s", pt)
            except Exception as exc:
                _log.debug("install monitor ocr fail: %s", exc)
            finally:
                try:
                    if shot.is_file():
                        shot.unlink()
                except OSError:
                    pass
        stop.wait(0.5)
