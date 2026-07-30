"""Entry-screen gate: foreground watch + DeepSeek OCR agent."""

from __future__ import annotations

import hashlib
import logging
import tempfile
import time
from concurrent.futures import Future, ThreadPoolExecutor
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
    timeout_sec: float = 1200,
    poll_sec: float = 3.0,
    agent_interval_sec: float = 3.0,
    foreground_poll_sec: float = 1.5,
    thread_id: str | None = None,
) -> str:
    """
    Navigate privacy/download via small_agent until login/start/server entry.
    Returns scene label, or crash / ai_unavailable. Raises TimeoutError on budget.
    """
    from small_agent import UiAgentSession, ping_model
    from small_agent.tools import FrameOutcome

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
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ui-decide")
    decide_future: Future | None = None
    try:
        if not ping_model():
            return "ai_unavailable"

        session = UiAgentSession(adb, thread_id=thread_id)
        session.bootstrap()

        deadline = time.monotonic() + timeout_sec
        shot_dir = Path(tempfile.mkdtemp(prefix="ocr_gate_"))
        last_fp = ""
        last_decide_at = 0.0
        note = ""
        n = 0
        print(
            f"ocr gate watching screen (small_agent, interval={agent_interval_sec}s)...",
            flush=True,
        )

        while time.monotonic() < deadline:
            n += 1
            action = watch.apply(watch.poll())
            if action == "crash":
                print("ocr gate: crash detected", flush=True)
                return "crash"
            if action == "brought_back":
                note = "just brought back from external/background UI"

            # Prior decide still thinking → skip this tick, never start another.
            if decide_future is not None and not decide_future.done():
                if n == 1 or n % 5 == 0:
                    print(f"ocr gate skip: decide still running poll={n}", flush=True)
                time.sleep(poll_sec)
                continue

            if decide_future is not None:
                try:
                    outcome = decide_future.result()
                except Exception as exc:
                    _log.warning("decide worker failed: %s", exc)
                    print(f"ocr gate decide error: {exc}", flush=True)
                    outcome = FrameOutcome(kind="wait")
                decide_future = None
                last_decide_at = time.monotonic()
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
                time.sleep(poll_sec)
                continue

            now = time.monotonic()
            wait_for = agent_interval_sec - (now - last_decide_at)
            if last_decide_at > 0 and wait_for > 0:
                time.sleep(min(wait_for, poll_sec))
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
                if n == 1 or n % 5 == 0:
                    print(f"ocr gate unchanged; wait poll={n}", flush=True)
                time.sleep(poll_sec)
                continue
            last_fp = fp

            submit_note = note
            note = ""
            decide_future = executor.submit(
                session.decide,
                items,
                poll=n,
                note=submit_note,
            )
            print(f"ocr gate decide submitted poll={n}", flush=True)

        print(f"ocr gate timeout after {timeout_sec}s", flush=True)
        raise TimeoutError(
            f"OCR gate timeout after {timeout_sec}s; entry screen not reached"
        )
    finally:
        watch.stop()
        if decide_future is not None and not decide_future.done():
            print("ocr gate waiting in-flight decide to finish...", flush=True)
            try:
                decide_future.result(timeout=120)
            except Exception as exc:
                _log.warning("in-flight decide end: %s", exc)
        executor.shutdown(wait=False)
