"""
Debuggable APK prep (no apktool / no smali decode):

1) Binary-patch AndroidManifest.xml to set android:debuggable=true
2) zipalign + apksigner
3) Zip-extract APK into decoded/ for the extract agent (resources only)

Manifest patcher adapted from julKali/makeDebuggable (with bugfix).
"""

from __future__ import annotations

import builtins
import io
import logging
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import config
from androguard.core.apk import APK
from prep.workspace import rmtree_force

_log = logging.getLogger(__name__)

_PKG_BADGING_RE = re.compile(r"package: name='([^']+)'")

_vendor = Path(__file__).resolve().parent / "_vendor"
if str(_vendor) not in sys.path:
    sys.path.insert(0, str(_vendor))
import makeDebuggable as md  # type: ignore


def _resolve_cmd(exe: str) -> str:
    found = shutil.which(exe)
    return found or exe


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    resolved = [_resolve_cmd(cmd[0]), *cmd[1:]]
    _log.info("run: %s", " ".join(resolved))
    use_bat = resolved[0].lower().endswith((".bat", ".cmd"))
    popen_cmd: list[str] = (["cmd", "/c", *resolved] if use_bat else resolved)
    result = subprocess.run(
        popen_cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
        )
    return result


def package_name_from_apk(apk_path: Path) -> str:
    """Resolve package name via aapt, fallback to androguard."""
    aapt = _find_aapt()
    if aapt:
        try:
            result = _run([aapt, "dump", "badging", str(apk_path)], timeout=120)
            match = _PKG_BADGING_RE.search(result.stdout or "")
            if match:
                return match.group(1)
        except RuntimeError as exc:
            _log.warning("aapt badging failed: %s", exc)

    # Quiet androguard (very noisy by default)
    logging.getLogger("androguard").setLevel(logging.WARNING)
    return APK(str(apk_path)).get_package() or ""


def extract_apk_zip(apk_path: Path, out_dir: Path) -> Path:
    """Extract APK as zip into decoded/ (no smali decompile)."""
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rmtree_force(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(apk_path, "r") as zf:
        zf.extractall(out_dir)
    _log.info("extracted apk zip -> %s", out_dir)
    return out_dir


def _patch_manifest_bytes(raw: bytes) -> bytes:
    out = io.BytesIO()
    real_print = builtins.print
    builtins.print = lambda *args, **kwargs: None
    try:
        md.patchManifest(io.BytesIO(raw), out)
    finally:
        builtins.print = real_print
    patched = out.getvalue()
    if not patched:
        raise RuntimeError("manifest patch produced empty output")
    return patched


def make_debuggable_signed_apk(src_apk: Path, out_apk: Path) -> Path:
    """
    Copy APK, binary-patch AndroidManifest debuggable=true, drop META-INF,
    zipalign, and sign with debug keystore.
    """
    src_apk = Path(src_apk)
    out_apk = Path(out_apk)
    if out_apk.exists():
        out_apk.unlink()

    unsigned = out_apk.with_suffix(".unsigned.apk")
    if unsigned.exists():
        unsigned.unlink()

    with zipfile.ZipFile(src_apk, "r") as zin:
        try:
            manifest_raw = zin.read("AndroidManifest.xml")
        except KeyError as exc:
            raise RuntimeError(f"APK missing AndroidManifest.xml: {src_apk}") from exc
        patched_manifest = _patch_manifest_bytes(manifest_raw)
        _log.info(
            "patched AndroidManifest.xml %s -> %s bytes",
            len(manifest_raw),
            len(patched_manifest),
        )

        with zipfile.ZipFile(unsigned, "w") as zout:
            man_info = zipfile.ZipInfo(filename="AndroidManifest.xml")
            man_info.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(man_info, patched_manifest)
            for info in zin.infolist():
                name = info.filename
                if name == "AndroidManifest.xml" or name.startswith("META-INF/"):
                    continue
                if name.endswith("/"):
                    continue
                data = zin.read(name)
                out_info = zipfile.ZipInfo(filename=name, date_time=info.date_time)
                out_info.compress_type = info.compress_type
                out_info.external_attr = info.external_attr
                zout.writestr(out_info, data)

    return _align_and_sign(unsigned, out_apk)


def _align_and_sign(unsigned: Path, out_apk: Path) -> Path:
    ks = _ensure_debug_keystore()
    apksigner_cmd = _apksigner_cmd()
    aligned = out_apk.with_suffix(".aligned.apk")
    src = unsigned
    zipalign = _find_zipalign()
    if zipalign:
        _run([zipalign, "-f", "4", str(unsigned), str(aligned)], timeout=120)
        src = aligned

    if apksigner_cmd:
        _run(
            [
                *apksigner_cmd,
                "sign",
                "--ks",
                str(ks),
                "--ks-pass",
                "pass:android",
                "--key-pass",
                "pass:android",
                "--ks-key-alias",
                "androiddebugkey",
                "--out",
                str(out_apk),
                str(src),
            ],
            timeout=180,
        )
    else:
        _run(
            [
                "jarsigner",
                "-keystore",
                str(ks),
                "-storepass",
                "android",
                "-keypass",
                "android",
                str(src),
                "androiddebugkey",
            ],
            timeout=180,
        )
        Path(src).replace(out_apk)

    for tmp in (unsigned, aligned):
        if tmp.exists() and tmp != out_apk:
            try:
                tmp.unlink()
            except OSError:
                pass
    if not out_apk.is_file():
        raise RuntimeError(f"signed apk missing: {out_apk}")
    _log.info("signed apk: %s", out_apk)
    return out_apk


def _ensure_debug_keystore() -> Path:
    ks = config.DEBUG_KEYSTORE
    if ks.is_file():
        return ks
    ks.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "keytool",
            "-genkeypair",
            "-v",
            "-keystore",
            str(ks),
            "-storepass",
            "android",
            "-keypass",
            "android",
            "-alias",
            "androiddebugkey",
            "-keyalg",
            "RSA",
            "-keysize",
            "2048",
            "-validity",
            "10000",
            "-dname",
            "CN=Android Debug,O=Android,C=US",
        ],
        timeout=120,
    )
    return ks


def _build_tools_dirs() -> list[Path]:
    sdk = Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "build-tools"
    if not sdk.is_dir():
        return []
    return sorted((p for p in sdk.iterdir() if p.is_dir()), reverse=True)


def _find_aapt() -> str | None:
    found = shutil.which("aapt") or shutil.which("aapt.exe")
    if found:
        return found
    for ver in _build_tools_dirs():
        for name in ("aapt.exe", "aapt"):
            candidate = ver / name
            if candidate.is_file():
                return str(candidate)
    return None


def _apksigner_cmd() -> list[str] | None:
    for ver in _build_tools_dirs():
        jar = ver / "lib" / "apksigner.jar"
        if jar.is_file():
            java = shutil.which("java") or "java"
            return [java, "-jar", str(jar)]
    found = shutil.which("apksigner")
    if found:
        return [found]
    for ver in _build_tools_dirs():
        for name in ("apksigner.bat", "apksigner"):
            candidate = ver / name
            if candidate.is_file():
                return [str(candidate)]
    return None


def _find_zipalign() -> str | None:
    found = shutil.which("zipalign")
    if found:
        return found
    for ver in _build_tools_dirs():
        for name in ("zipalign.exe", "zipalign"):
            candidate = ver / name
            if candidate.is_file():
                return str(candidate)
    return None
