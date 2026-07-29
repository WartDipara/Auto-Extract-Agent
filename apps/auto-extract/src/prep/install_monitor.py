from __future__ import annotations

import logging
import re
import tempfile
import threading
import time
from pathlib import Path

from prep.adb_device import AdbDevice
from prep.ocr_util import find_tap_for_texts, ocr_image
from prep.screen_coord import resolve_screen_coord_space

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


def install_apk_with_xiaomi_monitor(adb: AdbDevice, apk_path: Path, timeout: int = 600):
    brand = adb.brand()
    manufacturer = ""
    try:
        manufacturer = adb.shell("getprop ro.product.manufacturer").lower()
    except Exception:
        pass
    need_monitor = bool(
        re.search(r"xiaomi|redmi|poco", brand)
        or re.search(r"xiaomi|redmi|poco", manufacturer)
    )
    stop = threading.Event()
    thread = None
    if need_monitor:
        print("install monitor on (xiaomi dialog)", flush=True)
        shot_dir = Path(tempfile.mkdtemp(prefix="install_mon_"))
        thread = threading.Thread(
            target=_monitor_loop,
            args=(adb, stop, shot_dir),
            name="xiaomi-install-monitor",
            daemon=True,
        )
        thread.start()
        _log.info("xiaomi install monitor started brand=%s", brand or manufacturer)
    try:
        print(f"adb install {apk_path.name}", flush=True)
        adb.install(apk_path, timeout=timeout)
        print("adb install ok", flush=True)
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=10)


def _monitor_loop(adb: AdbDevice, stop: threading.Event, shot_dir: Path):
    try:
        import uiautomator2 as u2

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
        # OCR fallback only every 5th miss — install dialogs are almost always u2-visible
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
