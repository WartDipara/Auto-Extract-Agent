"""
Debuggable APK prep (no apktool / no smali decode):

1) Binary-patch AndroidManifest.xml to set android:debuggable=true
2) Rewrite APK keeping other entries' compressed bytes as-is (drop META-INF)
3) zipalign (skipped for huge/ZIP64 packs) + apksigner

Manifest patcher adapted from julKali/makeDebuggable (with bugfix).
"""

from __future__ import annotations

import builtins
import copy
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
# Classic ZIP / zipalign often break past 2GiB (ZIP64). Skip align for huge APKs.
_ZIPALIGN_MAX_BYTES = 2 * 1024 * 1024 * 1024
_ZIP64_THRESH = 0xFFFFFFFF

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
    Patch AndroidManifest debuggable=true, drop META-INF, keep other zip
    entries' compressed bytes unchanged, then zipalign (when safe) + sign.
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
        entries = [
            info
            for info in zin.infolist()
            if info.filename != "AndroidManifest.xml"
            and not info.filename.startswith("META-INF/")
            and not info.filename.endswith("/")
        ]

    _rewrite_apk_keep_compressed(
        src_apk,
        unsigned,
        entries=entries,
        manifest_bytes=patched_manifest,
    )
    _log.info("rewrote apk (raw entry copy, META-INF stripped): %s", unsigned)
    return _align_and_sign(unsigned, out_apk)


def _read_compressed_payload(apk: Path, info: zipfile.ZipInfo) -> bytes:
    """Read one entry's on-disk compressed payload (no decompress)."""
    with apk.open("rb") as f:
        f.seek(info.header_offset)
        local = f.read(30)
        if local[:4] != b"PK\x03\x04":
            raise RuntimeError(f"bad zip local header: {info.filename}")
        fname_len = int.from_bytes(local[26:28], "little")
        extra_len = int.from_bytes(local[28:30], "little")
        f.read(fname_len + extra_len)
        payload = f.read(info.compress_size)
    if len(payload) != info.compress_size:
        raise RuntimeError(
            f"truncated zip payload for {info.filename}: "
            f"{len(payload)} != {info.compress_size}"
        )
    return payload


def _strip_zip64_extra(extra: bytes) -> bytes:
    """Drop ZIP64 extra fields so FileHeader can rewrite them cleanly."""
    out = bytearray()
    i = 0
    while i + 4 <= len(extra):
        header_id = int.from_bytes(extra[i : i + 2], "little")
        data_size = int.from_bytes(extra[i + 2 : i + 4], "little")
        end = i + 4 + data_size
        if end > len(extra):
            break
        if header_id != 0x0001:
            out.extend(extra[i:end])
        i = end
    return bytes(out)


def _write_precompressed(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, compressed: bytes
) -> None:
    """Append an entry using already-compressed bytes (stdlib has no public API)."""
    zinfo = copy.copy(info)
    zinfo.compress_size = len(compressed)
    zinfo.extra = _strip_zip64_extra(zinfo.extra)
    # Size known; don't use data-descriptor streaming form.
    zinfo.flag_bits &= ~0x08
    zf._writecheck(zinfo)
    zf._didModify = True
    fp = zf.fp
    assert fp is not None
    zinfo.header_offset = fp.tell()
    zip64 = zinfo.file_size > _ZIP64_THRESH or zinfo.compress_size > _ZIP64_THRESH
    if zip64 and not zf._allowZip64:
        raise RuntimeError(f"zip64 required for entry: {zinfo.filename}")
    fp.write(zinfo.FileHeader(zip64))
    fp.write(compressed)
    zf.filelist.append(zinfo)
    zf.NameToInfo[zinfo.filename] = zinfo
    zf.start_dir = fp.tell()


def _rewrite_apk_keep_compressed(
    src_apk: Path,
    dst_apk: Path,
    *,
    entries: list[zipfile.ZipInfo],
    manifest_bytes: bytes,
) -> None:
    """Build dst APK: patched manifest + raw-copied entries (no META-INF)."""
    with zipfile.ZipFile(dst_apk, "w", allowZip64=True) as zout:
        man_info = zipfile.ZipInfo(filename="AndroidManifest.xml")
        man_info.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(man_info, manifest_bytes)
        for info in entries:
            payload = _read_compressed_payload(src_apk, info)
            _write_precompressed(zout, info, payload)


def _align_and_sign(unsigned: Path, out_apk: Path) -> Path:
    ks = _ensure_debug_keystore()
    apksigner_cmd = _apksigner_cmd()
    aligned = out_apk.with_suffix(".aligned.apk")
    src = unsigned
    zipalign = _find_zipalign()
    size = unsigned.stat().st_size if unsigned.is_file() else 0
    if zipalign and size >= _ZIPALIGN_MAX_BYTES:
        _log.warning(
            "skip zipalign for large apk (%s bytes >= %s); signing without align",
            size,
            _ZIPALIGN_MAX_BYTES,
        )
    elif zipalign:
        try:
            _run([zipalign, "-f", "4", str(unsigned), str(aligned)], timeout=120)
            src = aligned
        except RuntimeError as exc:
            # Large/ZIP64 packs often fail with "Unable to open ... as zip archive".
            msg = str(exc).lower()
            if "as zip archive" in msg or size >= _ZIPALIGN_MAX_BYTES // 2:
                _log.warning("zipalign failed; signing without align: %s", exc)
                src = unsigned
            else:
                raise

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
