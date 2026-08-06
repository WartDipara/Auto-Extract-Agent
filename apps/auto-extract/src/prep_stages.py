from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import config
from downloader import download
from errors import TaskError
from shared.archive_contract import task_layout
from shared.prep.adb_device import AdbDevice
from shared.prep.debuggable_apk import (
    extract_apk_zip,
    make_debuggable_signed_apk,
    package_name_from_apk,
)
from shared.prep.device_handlers import register_device_handlers
from shared.prep.device_router import dispatch as dispatch_device
from shared.prep.hotfix_pull import hotfix_has_content, pull_hotfix_candidates
from shared.prep.ocr_gate import wait_until_entry_screen
from shared.prep.workspace import clear_signed_apks

register_device_handlers()

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


@dataclass
class PatchResult:
    package_name: str
    apk_stem: str
    original_apk: Path
    signed_apk: Path
    decoded_dir: Path
    task_root: Path


def run_patch_stage(*, task_root: Path, apk_path: Path) -> PatchResult:
    layout = task_layout(task_root)
    clear_signed_apks(task_root)
    apk_path = Path(apk_path)
    if not apk_path.is_file():
        raise TaskError(
            code="PREP_APK_MISSING",
            message=f"apk not found: {apk_path}",
            details={"apk_path": str(apk_path)},
        )
    stem = apk_path.stem
    stage(f"apk ready {apk_path.name}")
    package_name = package_name_from_apk(apk_path)
    if not package_name:
        raise TaskError(
            code="PREP_PACKAGE",
            message="cannot resolve package name from apk",
            details={"apk": apk_path.name},
        )
    stage(f"package {package_name}")
    stage("extracting apk zip -> decoded/ ...")
    decoded = extract_apk_zip(apk_path, layout["decoded"])
    stage("decoded extract finished")
    signed = Path(task_root) / f"{stem}_signed.apk"
    stage("patching debuggable + signing...")
    make_debuggable_signed_apk(apk_path, signed)
    stage(f"signed apk ready {signed.name}")
    layout["hotfix"].mkdir(parents=True, exist_ok=True)
    return PatchResult(
        package_name=package_name,
        apk_stem=stem,
        original_apk=apk_path,
        signed_apk=signed,
        decoded_dir=decoded,
        task_root=Path(task_root),
    )


def run_device_stage(
    *,
    task_root: Path,
    apk_path: Path,
    signed_apk: Path,
    package_name: str,
    serial: str,
    skip_ocr_gate: bool = False,
) -> PrepResult:
    layout = task_layout(task_root)
    apk_path = Path(apk_path)
    signed_apk = Path(signed_apk)
    stem = apk_path.stem
    adb = AdbDevice(serial=serial)
    stage(f"adb device ready {serial}")
    try:
        if adb.ensure_uninstalled(package_name):
            stage(f"uninstalled existing {package_name}")
    except Exception as exc:
        _log.warning(
            "ensure_uninstalled before install failed (continue install): %s",
            exc,
        )
        stage(f"pre-uninstall warning; continue install: {exc}")
    stage(f"installing {signed_apk.name}")
    try:
        dispatch_device(adb).install_apk(
            adb, signed_apk, package_name=package_name
        )
    except TaskError:
        raise
    except Exception as exc:
        raise TaskError(
            code="PREP_INSTALL",
            message=str(exc) or "apk install failed",
            details={
                "package": package_name,
                "serial": adb.serial,
                "handler": adb.device_handler.name,
            },
            cause=exc,
        ) from exc
    stage("install finished")
    stage("starting game...")
    try:
        adb.launch_package(package_name)
    except Exception as exc:
        _log.warning("launch_package failed (still try gate/pull): %s", exc)
        stage(f"launch failed; continue prep soft path: {exc}")
    gate_timeout = float(config.PREP_GATE_TIMEOUT_SEC)
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
        except Exception as exc:
            screen_reached = "gate_error"
            _log.exception("ocr gate unexpected failure: %s", exc)
            stage(f"ocr gate failed; still attempting hotfix pull: {exc}")
    stage("pulling hotfix...")
    try:
        pull_source = pull_hotfix_candidates(adb, package_name, layout["hotfix"])
    except Exception as exc:
        # Belt-and-suspenders: pull_hotfix_candidates should not raise.
        pull_source = "error"
        _log.exception("hotfix pull raised: %s", exc)
        stage(f"hotfix pull failed (continue without): {exc}")
        layout["hotfix"].mkdir(parents=True, exist_ok=True)
    stage(f"hotfix pull finished source={pull_source}")
    try:
        adb.force_stop(package_name)
    except Exception as exc:
        _log.warning("force_stop after prep: %s", exc)
    try:
        adb.ensure_uninstalled(package_name)
    except Exception as exc:
        _log.warning("uninstall after prep: %s", exc)
    has_files = hotfix_has_content(layout["hotfix"])
    stage(
        f"device stage done hotfix_files={'yes' if has_files else 'no'} "
        f"source={pull_source} screen={screen_reached}"
    )
    return PrepResult(
        package_name=package_name,
        apk_stem=stem,
        original_apk=apk_path,
        signed_apk=signed_apk,
        decoded_dir=layout["decoded"],
        hotfix_dir=layout["hotfix"],
        hotfix_has_files=has_files,
        pull_source=pull_source,
        task_root=Path(task_root),
        screen_reached=screen_reached,
    )


def run_device_prep(
    *,
    task_root: Path,
    url: str | None = None,
    apk_path: Path | None = None,
    serial: str | None = None,
    skip_ocr_gate: bool = False,
) -> PrepResult:
    if not url and not apk_path:
        raise TaskError(code="PREP_ARGS", message="url or apk_path required")
    if apk_path is None:
        apk_path = download(url)
    else:
        stage(f"using local apk {Path(apk_path).name}")
    patch = run_patch_stage(task_root=task_root, apk_path=Path(apk_path))
    adb = AdbDevice(serial=serial or config.ADB_SERIAL or None)
    online = adb.list_online_devices()
    if not online or (adb.serial and adb.serial not in online):
        detail = (
            f"ADB_SERIAL={adb.serial} not online; online={online}"
            if adb.serial
            else f"online={online}"
        )
        stage(f"no adb device ({detail}); skip install/hotfix")
        layout = task_layout(task_root)
        layout["hotfix"].mkdir(parents=True, exist_ok=True)
        return PrepResult(
            package_name=patch.package_name,
            apk_stem=patch.apk_stem,
            original_apk=patch.original_apk,
            signed_apk=patch.signed_apk,
            decoded_dir=patch.decoded_dir,
            hotfix_dir=layout["hotfix"],
            hotfix_has_files=False,
            pull_source="none",
            task_root=Path(task_root),
            screen_reached="no_device",
        )
    serial_used = adb.require_one_device()
    return run_device_stage(
        task_root=task_root,
        apk_path=patch.original_apk,
        signed_apk=patch.signed_apk,
        package_name=patch.package_name,
        serial=serial_used,
        skip_ocr_gate=skip_ocr_gate,
    )
