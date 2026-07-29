from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from prep.adb_device import AdbDevice
from prep.workspace import rmtree_force

_log = logging.getLogger(__name__)

# /data/data/.../files exclusions (names)
_DATA_EXCLUDE_NAMES = {
    "oat",
    "lib",
    ".0000000",
    ".111111",
    "crashsdk",
    "filedownloader",
}
# ShadowPluginManager / ShadowPlugin_* 等一律不拉
_DATA_EXCLUDE_PREFIXES = ("ShadowPlugin",)

# Android/data/.../files exclusions
_SDCARD_EXCLUDE_NAMES = {
    "il2cpp",
    "plugin",
}
_SDCARD_EXCLUDE_PREFIXES = ("ShadowPlugin",)


def _excluded(name: str, *, sdcard: bool) -> bool:
    if name in (_SDCARD_EXCLUDE_NAMES if sdcard else _DATA_EXCLUDE_NAMES):
        return True
    prefixes = _SDCARD_EXCLUDE_PREFIXES if sdcard else _DATA_EXCLUDE_PREFIXES
    return any(name.startswith(p) for p in prefixes)


def hotfix_has_content(hotfix_dir: Path) -> bool:
    if not hotfix_dir.is_dir():
        return False
    for path in hotfix_dir.rglob("*"):
        if path.is_file() and path.stat().st_size > 0:
            return True
    return False


_INTERNAL_SUBDIR = "internal_storage"
_SDCARD_SUBDIR = "sdcard"


def pull_hotfix_candidates(adb: AdbDevice, package: str, hotfix_dir: Path) -> str:
    """
    Pull both device locations into hotfix_dir subfolders:
      internal_storage/  <- /data/data/<pkg>/files
      sdcard/            <- /sdcard/Android/data/<pkg>/files
    Returns pull_source: internal_storage | sdcard | internal_storage+sdcard | none
    """
    rmtree_force(hotfix_dir)
    hotfix_dir.mkdir(parents=True, exist_ok=True)
    sources: list[str] = []

    internal_dir = hotfix_dir / _INTERNAL_SUBDIR
    internal_dir.mkdir(parents=True, exist_ok=True)
    print("pulling hotfix from /data/data/.../files -> internal_storage/", flush=True)
    if _try_pull_run_as(adb, package, internal_dir) and hotfix_has_content(internal_dir):
        sources.append(_INTERNAL_SUBDIR)
        print("hotfix pulled from data/data -> internal_storage/", flush=True)
    else:
        rmtree_force(internal_dir)

    sdcard_dir = hotfix_dir / _SDCARD_SUBDIR
    sdcard_dir.mkdir(parents=True, exist_ok=True)
    print("pulling hotfix from Android/data/.../files -> sdcard/", flush=True)
    if _try_pull_android_data(adb, package, sdcard_dir) and hotfix_has_content(sdcard_dir):
        sources.append(_SDCARD_SUBDIR)
        print("hotfix pulled from Android/data -> sdcard/", flush=True)
    else:
        rmtree_force(sdcard_dir)

    if not sources:
        print("hotfix pull empty", flush=True)
        _log.warning("no hotfix content pulled for %s", package)
        return "none"
    result = "+".join(sources)
    _log.info("hotfix pull sources=%s", result)
    return result


def _try_pull_run_as(adb: AdbDevice, package: str, hotfix_dir: Path) -> bool:
    remote_files = f"/data/data/{package}/files"
    try:
        listing = adb.shell(f"run-as {package} ls -p {remote_files}")
    except RuntimeError as exc:
        _log.info("run-as list failed: %s", exc)
        return False

    dirs = []
    for ln in listing.splitlines():
        name = ln.strip()
        if not name:
            continue
        is_dir = name.endswith("/")
        name = name.rstrip("/")
        if not is_dir or _excluded(name, sdcard=False):
            continue
        dirs.append(name)
    if not dirs:
        _log.info("run-as: no candidate dirs under files/")
        return True

    ok_any = False
    for name in dirs:
        remote_dir = f"{remote_files}/{name}"
        local_dir = hotfix_dir / name
        local_dir.mkdir(parents=True, exist_ok=True)
        if _pull_run_as_dir_tar(adb, package, remote_files, name, hotfix_dir):
            ok_any = True
            continue
        if _pull_run_as_dir_files(adb, package, remote_dir, local_dir):
            ok_any = True
            continue
        _log.warning("run-as pull failed for dir %s", name)
    return ok_any


def _pull_run_as_dir_tar(
    adb: AdbDevice,
    package: str,
    remote_files: str,
    name: str,
    hotfix_dir: Path,
) -> bool:
    staging = Path(tempfile.mkdtemp(prefix="hotfix_tar_"))
    local_tar = staging / f"{name}.tar"
    try:
        cmd = adb._base() + [
            "exec-out",
            "run-as",
            package,
            "tar",
            "-cf",
            "-",
            "-C",
            remote_files,
            name,
        ]
        _log.info("pull via run-as tar: %s", name)
        with local_tar.open("wb") as fp:
            proc = subprocess.run(cmd, stdout=fp, stderr=subprocess.PIPE, timeout=600)
        if proc.returncode != 0 or not local_tar.is_file() or local_tar.stat().st_size == 0:
            _log.info(
                "tar pull unavailable for %s: %s",
                name,
                (proc.stderr or b"")[-300:],
            )
            return False
        # Windows 11 includes tar.exe
        extract = subprocess.run(
            ["tar", "-xf", str(local_tar), "-C", str(hotfix_dir)],
            capture_output=True,
            timeout=300,
        )
        if extract.returncode != 0:
            _log.warning("local tar extract failed: %s", extract.stderr[-300:])
            return False
        return (hotfix_dir / name).exists()
    except Exception as exc:
        _log.info("tar pull exception for %s: %s", name, exc)
        return False
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _pull_run_as_dir_files(
    adb: AdbDevice,
    package: str,
    remote_dir: str,
    local_dir: Path,
) -> bool:
    """Fallback: find + exec-out cat each file (works without device tar)."""
    try:
        listing = adb.shell(f"run-as {package} find {remote_dir} -type f")
    except RuntimeError as exc:
        _log.info("run-as find failed: %s", exc)
        return False
    files = [ln.strip() for ln in listing.splitlines() if ln.strip()]
    if not files:
        return False
    pulled = 0
    for remote_file in files:
        if not remote_file.startswith(remote_dir):
            continue
        rel = remote_file[len(remote_dir) :].lstrip("/")
        if not rel:
            continue
        dest = local_dir / rel.replace("/", "\\")
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = adb._base() + ["exec-out", "run-as", package, "cat", remote_file]
        try:
            with dest.open("wb") as fp:
                proc = subprocess.run(cmd, stdout=fp, stderr=subprocess.PIPE, timeout=300)
            if proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 0:
                pulled += 1
            else:
                try:
                    dest.unlink()
                except OSError:
                    pass
        except Exception as exc:
            _log.debug("cat pull failed %s: %s", remote_file, exc)
    _log.info("run-as file pull: %s files from %s", pulled, remote_dir)
    return pulled > 0


def _try_pull_android_data(adb: AdbDevice, package: str, hotfix_dir: Path) -> bool:
    candidates = [
        f"/sdcard/Android/data/{package}/files",
        f"/storage/emulated/0/Android/data/{package}/files",
    ]
    remote = None
    listing = ""
    for path in candidates:
        try:
            listing = adb.shell(f"ls -p {path}")
            remote = path
            break
        except RuntimeError:
            continue
    if remote is None:
        _log.info("android/data files not accessible")
        return False

    dirs = []
    for ln in listing.splitlines():
        name = ln.strip()
        if not name:
            continue
        is_dir = name.endswith("/")
        name = name.rstrip("/")
        if not is_dir or _excluded(name, sdcard=True):
            continue
        dirs.append(name)
    if not dirs:
        return True

    for name in dirs:
        # Pull into hotfix_dir so result is hotfix_dir/name/...
        try:
            adb.run(["pull", f"{remote}/{name}", str(hotfix_dir / name)], timeout=600)
            _log.info("pulled android/data dir %s", name)
        except RuntimeError as exc:
            _log.warning("pull %s failed: %s", name, exc)

    for name in dirs:
        nested = hotfix_dir / name / name
        parent = hotfix_dir / name
        if nested.is_dir() and parent.is_dir():
            for child in list(nested.iterdir()):
                target = parent / child.name
                if not target.exists():
                    shutil.move(str(child), str(target))
            rmtree_force(nested)
    return True
