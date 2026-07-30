"""Entry-screen gate: foreground watch + DeepSeek OCR agent."""

from __future__ import annotations

import hashlib
import logging
import tempfile
import time
from pathlib import Path

from prep.adb_device import AdbDevice
from prep.foreground_watch import ForegroundWatch
from prep.ocr_util import ocr_image, texts_joined
from prep.screen_coord import resolve_screen_coord_space

_log = logging.getLogger(__name__)


def wait_until_entry_screen(
    adb: AdbDevice,
    *,
    package_name: str,
    timeout_sec: float = 600,
    poll_sec: float = 0.8,
    foreground_poll_sec: float = 1.5,
    thread_id: str | None = None,
) -> str:
    """
    Navigate privacy/download via small_agent until login/start/server entry.
    Returns scene label, or crash / ai_unavailable. Raises TimeoutError on budget.
    """
    from small_agent import UiAgentSession, ping_model

    # Cold start may need a moment before pidof sees the process.
    if not adb.is_package_running(package_name):
        time.sleep(2.0)
    if not adb.is_package_running(package_name):
        print("ocr gate: package not running after launch", flush=True)
        return "crash"

    watch = ForegroundWatch(
        adb,
        package_name,
        poll_sec=foreground_poll_sec,
    )
    watch.start()
    try:
        if not ping_model():
            return "ai_unavailable"

        session = UiAgentSession(adb, thread_id=thread_id)
        session.bootstrap()

        deadline = time.monotonic() + timeout_sec
        shot_dir = Path(tempfile.mkdtemp(prefix="ocr_gate_"))
        last_fp = ""
        note = ""
        n = 0
        print("ocr gate watching screen (small_agent)...", flush=True)

        while time.monotonic() < deadline:
            n += 1
            action = watch.apply(watch.poll())
            if action == "crash":
                print("ocr gate: crash detected", flush=True)
                return "crash"
            if action == "brought_back":
                note = "just brought back from external/background UI"
                time.sleep(0.8)
                continue

            shot = shot_dir / f"gate_{n}.png"
            adb.screencap(shot)
            space = resolve_screen_coord_space(adb, shot)
            items = ocr_image(shot, device_w=space.tap_w, device_h=space.tap_h)
            blob = texts_joined(items)
            fp = hashlib.sha1(blob.encode("utf-8", errors="replace")).hexdigest()
            _log.info(
                "ocr gate poll=%s text_sample=%s",
                n,
                blob[:240].replace("\n", " | "),
            )

            if fp == last_fp:
                if n == 1 or n % 10 == 0:
                    print(f"ocr gate unchanged; wait poll={n}", flush=True)
                time.sleep(poll_sec)
                continue
            last_fp = fp

            outcome = session.decide(items, poll=n, note=note)
            note = ""
            print(
                f"ocr gate agent: {outcome.kind}"
                f"{' ' + outcome.scene if outcome.scene else ''}"
                f"{' id=' + str(outcome.item_id) if outcome.item_id is not None else ''}",
                flush=True,
            )
            if outcome.kind == "done":
                scene = outcome.scene or "entry"
                print(f"ocr gate hit entry: {scene}", flush=True)
                return scene
            if outcome.kind == "tap":
                time.sleep(0.6)
                continue
            time.sleep(poll_sec)

        print(f"ocr gate timeout after {timeout_sec}s", flush=True)
        raise TimeoutError(
            f"OCR gate timeout after {timeout_sec}s; entry screen not reached"
        )
    finally:
        watch.stop()
