from __future__ import annotations

import logging
import tempfile
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import config
from .adb_device import AdbDevice
from .foreground_watch import ForegroundWatch
from .gate_rules import content_fingerprint, try_local_action
from .ocr_util import ocr_image, texts_joined
from .screen_coord import resolve_screen_coord_space
from small_agent import UiAgentSession, ping_model
from small_agent.tools import FrameOutcome

_log = logging.getLogger(__name__)


def wait_until_entry_screen(
    adb: AdbDevice,
    *,
    package_name: str,
    timeout_sec: float = 1200,
    poll_sec: float = 3.0,
    agent_interval_sec: float = 10.0,
    foreground_poll_sec: float = 1.5,
    wait_cooldown_sec: float = 20.0,
    thread_id: str | None = None,
) -> str:
    """
    Navigate privacy/download until login/start/server entry.

    Local OCR rules run first; LLM is only used when rules cannot decide.
    Returns scene label, or crash / ai_unavailable / gate_error.
    Raises TimeoutError on budget.
    """
    if not adb.is_package_running(package_name):
        time.sleep(2.0)
    if not adb.is_package_running(package_name):
        print("ocr gate: package not running after launch", flush=True)
        return "crash"

    watch = ForegroundWatch(
        adb,
        package_name,
        poll_sec=foreground_poll_sec,
        crash_confirm=int(config.PREP_CRASH_CONFIRM),
        background_confirm=int(config.PREP_BACKGROUND_CONFIRM),
    )
    watch.start()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ui-decide")
    decide_future: Future | None = None
    session: UiAgentSession | None = None
    try:
        deadline = time.monotonic() + timeout_sec
        shot_dir = Path(tempfile.mkdtemp(prefix="ocr_gate_"))
        last_fp = ""
        last_decide_at = 0.0
        llm_cooldown_until = 0.0
        note = ""
        n = 0
        relaunches = 0
        relaunch_max = max(0, int(getattr(config, "PREP_GATE_RELAUNCH_MAX", 3)))
        cooldown = float(wait_cooldown_sec)
        print(
            f"ocr gate watching (rules-first, llm_interval={agent_interval_sec}s, "
            f"wait_cooldown={cooldown}s)...",
            flush=True,
        )

        def _ensure_session() -> UiAgentSession | None:
            nonlocal session
            if session is not None:
                return session
            try:
                if not ping_model():
                    return None
            except Exception as exc:
                _log.warning("ocr gate ping_model failed: %s", exc)
                return None
            session = UiAgentSession(adb, thread_id=thread_id)
            session.bootstrap()
            return session

        while time.monotonic() < deadline:
            n += 1
            try:
                action = watch.apply(watch.poll())
            except Exception as exc:
                _log.warning("ocr gate watch poll failed: %s", exc)
                time.sleep(poll_sec)
                continue
            if action == "crash":
                if relaunches < relaunch_max:
                    relaunches += 1
                    print(
                        f"ocr gate: process gone; relaunch "
                        f"{relaunches}/{relaunch_max} {package_name}",
                        flush=True,
                    )
                    _log.warning(
                        "ocr gate relaunch after process gap package=%s n=%s/%s",
                        package_name,
                        relaunches,
                        relaunch_max,
                    )
                    try:
                        adb.force_stop(package_name)
                    except Exception:
                        pass
                    time.sleep(1.0)
                    try:
                        adb.launch_package(package_name)
                    except Exception as exc:
                        _log.warning("ocr gate relaunch launch failed: %s", exc)
                    time.sleep(2.0)
                    try:
                        running = adb.is_package_running(package_name)
                    except Exception:
                        running = False
                    if running:
                        watch.reset()
                        decide_future = None
                        last_fp = ""
                        last_decide_at = 0.0
                        llm_cooldown_until = 0.0
                        if session is not None:
                            session.reset_memory()
                        note = (
                            "game process restarted after update/exit; "
                            "continue privacy/download/entry flow"
                        )
                        continue
                    _log.error(
                        "ocr gate relaunch failed; package still not running"
                    )
                print("ocr gate: crash detected", flush=True)
                return "crash"
            if action == "brought_back":
                note = "just brought back from external/background UI"

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
                if outcome.kind == "wait":
                    llm_cooldown_until = time.monotonic() + cooldown
                time.sleep(poll_sec)
                continue

            now = time.monotonic()
            if now < llm_cooldown_until:
                time.sleep(min(poll_sec, llm_cooldown_until - now))
                continue

            wait_for = agent_interval_sec - (now - last_decide_at)
            # Interval only gates LLM falls-through; local rules always allowed.
            # (Applied after OCR below when rules miss.)

            shot = shot_dir / f"gate_{n}.png"
            try:
                adb.screencap(shot)
                space = resolve_screen_coord_space(adb, shot)
                items = ocr_image(shot, device_w=space.tap_w, device_h=space.tap_h)
            except Exception as exc:
                _log.warning("ocr gate screencap/ocr failed poll=%s: %s", n, exc)
                print(f"ocr gate frame error poll={n}: {exc}", flush=True)
                time.sleep(poll_sec)
                continue

            blob = texts_joined(items)
            fp = content_fingerprint(items)
            _log.info(
                "ocr gate poll=%s text_sample=%s",
                n,
                blob[:240].replace("\n", " | "),
            )

            local = try_local_action(adb, items)
            if local is not None:
                print(
                    f"ocr gate rule: {local.kind}"
                    f"{' ' + local.scene if local.scene else ''}"
                    f"{' ' + local.text if local.text else ''} poll={n}",
                    flush=True,
                )
                if local.kind == "done":
                    scene = local.scene or "entry"
                    print(f"ocr gate hit entry: {scene}", flush=True)
                    return scene
                last_fp = fp
                last_decide_at = time.monotonic()
                if local.kind == "wait":
                    llm_cooldown_until = time.monotonic() + cooldown
                elif local.kind == "tap":
                    # Brief settle after tap before next OCR.
                    time.sleep(min(poll_sec, 1.5))
                else:
                    time.sleep(poll_sec)
                continue

            if fp == last_fp:
                if n == 1 or n % 5 == 0:
                    print(f"ocr gate unchanged; wait poll={n}", flush=True)
                time.sleep(poll_sec)
                continue

            if last_decide_at > 0 and wait_for > 0:
                time.sleep(min(wait_for, poll_sec))
                continue

            last_fp = fp
            agent = _ensure_session()
            if agent is None:
                print("ocr gate: ai unavailable for undecided frame", flush=True)
                return "ai_unavailable"

            submit_note = note
            note = ""
            decide_future = executor.submit(
                agent.decide,
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
        try:
            watch.stop()
        except Exception:
            pass
        if decide_future is not None and not decide_future.done():
            print("ocr gate waiting in-flight decide to finish...", flush=True)
            try:
                decide_future.result(timeout=120)
            except Exception as exc:
                _log.warning("in-flight decide end: %s", exc)
        executor.shutdown(wait=False)
