from __future__ import annotations

import logging
import re
import tempfile
import time
from pathlib import Path

from prep.adb_device import AdbDevice
from prep.ocr_util import find_tap_for_texts, ocr_image, texts_joined
from prep.screen_coord import resolve_screen_coord_space

_log = logging.getLogger(__name__)

# Modal-only titles. Bare 用户协议/隐私政策 appear as login footer links — do not use.
_PRIVACY_MODAL_TITLE = (
    "个人信息保护指引",
    "個人信息保護指引",
)
_PRIVACY_CONTEXT = (
    "隐私",
    "隱私",
    "用户协议",
    "用戶協議",
    "个人信息",
    "個人信息",
    "许可及服务",
    "隐私协议",
    "隱私協議",
    "隐私政策",
    "隱私政策",
)
_PRIVACY_AGREE = ("同意并进入", "同意並進入", "同意", "接受", "确认", "確認")
_DOWNLOAD_CONTEXT = (
    "正在下载",
    "正在下載",
    "下载中",
    "下載中",
    "资源下载",
    "資源下載",
    "更新资源",
    "更新資源",
    "立即下载",
    "立即下載",
    "下载更新",
    "下載更新",
)
# e.g. 3790KB/16478KB — common silent asset download UI with no "下载" label
_DOWNLOAD_PROGRESS_RE = re.compile(
    r"\d+(?:\.\d+)?\s*[KkMmGg]?[Bb]\s*/\s*\d+(?:\.\d+)?\s*[KkMmGg]?[Bb]"
)
_DOWNLOAD_CONTINUE = ("继续", "繼續", "确认", "確認", "立即下载", "立即下載", "更新")
# Strong entry: past splash privacy. Do NOT include 进入游戏/开始游戏 — privacy
# tip copy often says 「勾选后方可进入游戏」.
_STRONG_ENTRY = (
    "账号切换",
    "帳號切換",
    "重新登录",
    "重新登錄",
    "点击选区",
    "點擊選區",
    "选服",
    "選服",
    "点击选服",
    "忘记密码",
    "忘記密碼",
    "角色信息",
    "公会排行",
    "公會排行",
)
_ENTRY_MARKERS = _STRONG_ENTRY + (
    "登录",
    "登錄",
    "立即登录",
    "开始游戏",
    "開始遊戲",
    "进入游戏",
    "進入遊戲",
    "區服",
    "服务器",
    "服務器",
    "账号",
    "帳號",
    "密码",
    "密碼",
)

_u2_device = None


def _get_u2(adb: AdbDevice):
    global _u2_device
    if _u2_device is not None:
        return _u2_device
    try:
        import uiautomator2 as u2

        _u2_device = u2.connect(adb.serial) if adb.serial else u2.connect()
        return _u2_device
    except Exception as exc:
        _log.debug("u2 unavailable: %s", exc)
        return None


def wait_until_entry_screen(
    adb: AdbDevice,
    *,
    timeout_sec: float = 600,
    poll_sec: float = 0.8,
) -> str:
    """OCR/u2 loop: dismiss privacy modal, wait download, return on entry/login."""
    deadline = time.monotonic() + timeout_sec
    shot_dir = Path(tempfile.mkdtemp(prefix="ocr_gate_"))
    n = 0
    privacy_disabled = False
    print("ocr gate watching screen...", flush=True)
    while time.monotonic() < deadline:
        n += 1

        click_texts = (
            _DOWNLOAD_CONTINUE if privacy_disabled else (_PRIVACY_AGREE + _DOWNLOAD_CONTINUE)
        )
        if _u2_try_click(adb, click_texts):
            print("ocr gate: u2 clicked dialog button", flush=True)
            time.sleep(0.6)
            continue

        shot = shot_dir / f"gate_{n}.png"
        adb.screencap(shot)
        space = resolve_screen_coord_space(adb, shot)
        items = ocr_image(shot, device_w=space.tap_w, device_h=space.tap_h)
        blob = texts_joined(items)
        _log.info("ocr gate poll=%s text_sample=%s", n, blob[:240].replace("\n", " | "))

        # Download / update progress → past splash privacy; just wait.
        if _is_download_screen(blob):
            if not privacy_disabled:
                privacy_disabled = True
                print("ocr gate: download/update seen -> skip privacy thereafter", flush=True)
                _log.info("privacy disabled: download/update seen")
            pt = find_tap_for_texts(items, _DOWNLOAD_CONTINUE)
            if pt:
                adb.tap(*pt)
                print("ocr gate: tapped download/update continue", flush=True)
                _log.info("tapped download/update continue at %s", pt)
                time.sleep(0.8)
            elif n == 1 or n % 10 == 0:
                print(f"ocr gate waiting download... poll={n}", flush=True)
            time.sleep(poll_sec)
            continue

        # Strong entry wins over footer 「阅读并同意 / 隐私协议」.
        if _match_any(blob, _STRONG_ENTRY) or _has_login_features(blob):
            if not privacy_disabled:
                privacy_disabled = True
                print("ocr gate: entry/login seen -> skip privacy thereafter", flush=True)
                _log.info("privacy disabled: entry/login seen")
            kind = _classify_entry(blob)
            print(f"ocr gate hit entry: {kind}", flush=True)
            _log.info("entry screen reached: %s", kind)
            return kind

        if _match_any(blob, _ENTRY_MARKERS) and (
            privacy_disabled
            or not _is_privacy_modal(blob)
        ):
            kind = _classify_entry(blob)
            print(f"ocr gate hit entry: {kind}", flush=True)
            _log.info("entry screen reached: %s", kind)
            return kind

        # Splash privacy modal only (不同意|同意 pair / 个人信息保护指引).
        if not privacy_disabled and _is_privacy_modal(blob):
            pt = find_tap_for_texts(items, _PRIVACY_AGREE)
            if pt:
                adb.tap(*pt)
                print("ocr gate: tapped privacy agree", flush=True)
                _log.info("tapped privacy agree at %s", pt)
                time.sleep(0.6)
                continue
            if _u2_try_click(adb, _PRIVACY_AGREE):
                print("ocr gate: u2 clicked privacy agree", flush=True)
                time.sleep(0.6)
                continue

        if n == 1 or n % 10 == 0:
            print(f"ocr gate still waiting... poll={n}", flush=True)
        time.sleep(poll_sec)

    print(f"ocr gate timeout after {timeout_sec}s", flush=True)
    raise TimeoutError(f"OCR gate timeout after {timeout_sec}s; entry screen not reached")


def _match_any(blob: str, needles: tuple[str, ...]) -> bool:
    return any(n in blob for n in needles)


def _is_privacy_modal(blob: str) -> bool:
    """True only for splash privacy modals that need a dedicated 同意 tap."""
    if _match_any(blob, _STRONG_ENTRY):
        return False
    if _match_any(blob, _PRIVACY_MODAL_TITLE):
        return True
    # Disagree + Agree pair is the reliable modal signal.
    if "不同意" in blob and _match_any(blob, ("同意",)) and _match_any(blob, _PRIVACY_CONTEXT):
        return True
    return False


def _is_download_screen(blob: str) -> bool:
    if _is_privacy_modal(blob):
        return False
    if _match_any(blob, _DOWNLOAD_CONTEXT):
        return True
    return bool(_DOWNLOAD_PROGRESS_RE.search(blob))


def _has_login_features(blob: str) -> bool:
    if "忘记密码" in blob or "忘記密碼" in blob:
        return True
    has_account = "账号" in blob or "帳號" in blob
    has_password = "密码" in blob or "密碼" in blob
    if has_account and has_password:
        return True
    if "账号切换" in blob or "帳號切換" in blob:
        return True
    if "重新登录" in blob or "重新登錄" in blob:
        return True
    # Bare 登录 alone is weak (privacy tips may mention it); require non-modal.
    if ("登录" in blob or "登錄" in blob) and not _is_privacy_modal(blob):
        return True
    return False


def _classify_entry(blob: str) -> str:
    if any(x in blob for x in ("选服", "選服", "區服", "点击选区", "點擊選區", "服务器", "服務器")):
        return "server_select"
    if any(x in blob for x in ("开始游戏", "開始遊戲", "进入游戏", "進入遊戲")):
        return "start_game"
    if any(
        x in blob
        for x in ("登录", "登錄", "账号", "帳號", "密码", "密碼", "账号切换", "重新登录")
    ):
        return "login"
    return "entry"


def _u2_try_click(adb: AdbDevice, texts: tuple[str, ...]) -> bool:
    d = _get_u2(adb)
    if d is None:
        return False
    for text in texts:
        try:
            btn = d(text=text)
            if btn.exists(timeout=0.15):
                btn.click()
                _log.info("u2 gate click %r", text)
                return True
        except Exception:
            continue
    return False
