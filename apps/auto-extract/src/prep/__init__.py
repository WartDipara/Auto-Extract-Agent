"""Device preprocessing: debuggable resign / install / OCR gate / hotfix pull."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import config
from downloader import download
from prep.adb_device import AdbDevice
from prep.debuggable_apk import (
    extract_apk_zip,
    make_debuggable_signed_apk,
    package_name_from_apk,
)
from prep.hotfix_pull import hotfix_has_content, pull_hotfix_candidates
from prep.install_monitor import install_apk_with_xiaomi_monitor
from prep.ocr_gate import wait_until_entry_screen
from prep.workspace import clear_signed_apks
from shared.archive_contract import task_layout

_log = logging.getLogger(__name__)


def stage(msg: str) -> None:
    line = msg.strip()
    print(line, flush=True)
    _log.info("%s", line)


@dataclass
class PrepResult:
    package_name: str
    apk_stem: str
    original_apk: Path
    signed_apk: Path
    decoded_dir: Path
    hotfix_dir: Path
    hotfix_has_files: bool
    pull_source: str
    task_root: Path
    screen_reached: str = ""


def run_device_prep(
    *,
    task_root: Path,
    url: str | None = None,
    apk_path: Path | None = None,
    serial: str | None = None,
    skip_ocr_gate: bool = False,
) -> PrepResult:
    """Prep into an existing task_root (decoded/hotfix/outputs already created)."""
    if not url and not apk_path:
        raise ValueError("url or apk_path required")

    layout = task_layout(task_root)
    clear_signed_apks(task_root)

    if apk_path is None:
        apk_path = download(url)
    else:
        stage(f"using local apk {Path(apk_path).name}")

    apk_path = Path(apk_path)
    if not apk_path.is_file():
        raise FileNotFoundError(apk_path)

    stem = apk_path.stem
    stage(f"apk ready {apk_path.name}")

    stage("reading package name...")
    package_name = package_name_from_apk(apk_path)
    if not package_name:
        raise RuntimeError("cannot resolve package name from apk")
    stage(f"package {package_name}")

    stage("extracting apk zip -> decoded/ ...")
    decoded = extract_apk_zip(apk_path, layout["decoded"])
    stage("decoded extract finished")

    stage("checking adb device...")
    adb = AdbDevice(serial=serial or config.ADB_SERIAL or None)
    online = adb.list_online_devices()
    if not online or (adb.serial and adb.serial not in online):
        detail = (
            f"ADB_SERIAL={adb.serial} not online; online={online}"
            if adb.serial
            else f"online={online}"
        )
        stage(f"no adb device ({detail}); skip debuggable/install/hotfix")
        layout["hotfix"].mkdir(parents=True, exist_ok=True)
        return PrepResult(
            package_name=package_name,
            apk_stem=stem,
            original_apk=apk_path,
            signed_apk=apk_path,
            decoded_dir=decoded,
            hotfix_dir=layout["hotfix"],
            hotfix_has_files=False,
            pull_source="none",
            task_root=Path(task_root),
            screen_reached="no_device",
        )

    serial_used = adb.require_one_device()
    stage(f"adb device ready {serial_used}")

    stage(f"checking if installed {package_name}")
    if adb.ensure_uninstalled(package_name):
        stage(f"uninstalled existing {package_name}")
    else:
        stage("not installed on device")

    signed = Path(task_root) / f"{stem}_signed.apk"
    stage("patching debuggable + signing...")
    make_debuggable_signed_apk(apk_path, signed)
    stage(f"signed apk ready {signed.name}")

    stage(f"ensuring clean install {package_name}")
    adb.ensure_uninstalled(package_name)
    stage(f"installing {signed.name}")
    install_apk_with_xiaomi_monitor(adb, signed)
    stage("install finished")

    stage("starting game...")
    adb.launch_package(package_name)
    stage("game started")

    gate_timeout = float(config.PREP_GATE_TIMEOUT_SEC)
    stage(f"entry gate timeout {int(gate_timeout)}s (AI done / crash / safety)")

    screen_reached = "skipped"
    pull_source = "none"
    if not skip_ocr_gate:
        stage("waiting entry screen (ocr gate)...")
        try:
            screen_reached = wait_until_entry_screen(
                adb,
                package_name=package_name,
                timeout_sec=gate_timeout,
                poll_sec=config.PREP_OCR_POLL_SEC,
                agent_interval_sec=float(config.PREP_AGENT_INTERVAL_SEC),
                foreground_poll_sec=float(config.PREP_FOREGROUND_POLL_SEC),
            )
            stage(f"entry screen reached: {screen_reached}")
        except TimeoutError:
            screen_reached = "timeout"
            stage("ocr gate safety timeout; still attempting hotfix pull")

    stage("pulling hotfix...")
    pull_source = pull_hotfix_candidates(adb, package_name, layout["hotfix"])
    stage(f"hotfix pull finished source={pull_source}")

    stage("stopping game...")
    adb.force_stop(package_name)
    stage("game stopped")
    stage(f"uninstalling game {package_name}")
    adb.ensure_uninstalled(package_name)
    stage("game uninstalled")

    has_files = hotfix_has_content(layout["hotfix"])
    stage(f"prep done hotfix_files={'yes' if has_files else 'no'}")
    return PrepResult(
        package_name=package_name,
        apk_stem=stem,
        original_apk=apk_path,
        signed_apk=signed,
        decoded_dir=decoded,
        hotfix_dir=layout["hotfix"],
        hotfix_has_files=has_files,
        pull_source=pull_source,
        task_root=Path(task_root),
        screen_reached=screen_reached,
    )
