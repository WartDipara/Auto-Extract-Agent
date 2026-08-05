from __future__ import annotations

import enum
import logging
import threading
import time

from prep.adb_device import AdbDevice

_log = logging.getLogger(__name__)


class ForegroundState(enum.Enum):
    FOREGROUND = "foreground"
    BACKGROUNDED = "backgrounded"
    CRASHED = "crashed"


class ForegroundWatch:
    """Background thread keeps latest classify(); gate calls apply() each poll."""

    def __init__(
        self,
        adb: AdbDevice,
        package: str,
        *,
        poll_sec: float = 1.5,
        crash_confirm: int = 3,
        background_confirm: int = 2,
    ):
        self._adb = adb
        self._package = package
        self._poll_sec = poll_sec
        self._crash_confirm = max(1, int(crash_confirm))
        self._background_confirm = max(1, int(background_confirm))
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._state = ForegroundState.FOREGROUND
        self._crash_hits = 0
        self._background_hits = 0
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> ForegroundState:
        with self._lock:
            return self._state

    def classify_raw(self) -> ForegroundState:
        """One-shot observation without debounce."""
        if not self._adb.is_package_running(self._package):
            return ForegroundState.CRASHED
        focused = self._adb.foreground_package()
        if not focused or focused == self._package:
            return ForegroundState.FOREGROUND
        return ForegroundState.BACKGROUNDED

    def classify(self) -> ForegroundState:
        return self.classify_raw()

    def poll(self) -> ForegroundState:
        """Debounced state: brief Splash/focus gaps do not become crash/background."""
        raw = self.classify_raw()
        with self._lock:
            if raw is ForegroundState.CRASHED:
                self._crash_hits += 1
                self._background_hits = 0
                if self._crash_hits < self._crash_confirm:
                    _log.info(
                        "package process gap %s hit=%s/%s (ignore transient)",
                        self._package,
                        self._crash_hits,
                        self._crash_confirm,
                    )
                    print(
                        f"foreground watch: process gap {self._package} "
                        f"{self._crash_hits}/{self._crash_confirm}",
                        flush=True,
                    )
                    state = ForegroundState.FOREGROUND
                else:
                    state = ForegroundState.CRASHED
            elif raw is ForegroundState.BACKGROUNDED:
                self._crash_hits = 0
                self._background_hits += 1
                if self._background_hits < self._background_confirm:
                    _log.info(
                        "package focus gap %s hit=%s/%s (ignore transient)",
                        self._package,
                        self._background_hits,
                        self._background_confirm,
                    )
                    print(
                        f"foreground watch: focus gap {self._package} "
                        f"{self._background_hits}/{self._background_confirm}",
                        flush=True,
                    )
                    state = ForegroundState.FOREGROUND
                else:
                    state = ForegroundState.BACKGROUNDED
            else:
                self._crash_hits = 0
                self._background_hits = 0
                state = ForegroundState.FOREGROUND
            self._state = state
            return state

    def bring_back(self) -> None:
        print(f"foreground watch: bring back {self._package}", flush=True)
        _log.warning("package backgrounded; bringing to foreground %s", self._package)
        self._adb.bring_to_foreground(self._package)
        with self._lock:
            # Require a fresh background streak before monkey again.
            self._background_hits = 0

    def apply(self, state: ForegroundState | None = None) -> str | None:
        """
        Map state to action. Returns 'crash' | 'brought_back' | None.
        Open for new states without changing callers beyond this map.
        """
        current = state if state is not None else self.state
        if current is ForegroundState.CRASHED:
            print("foreground watch: package crashed", flush=True)
            _log.error("package process gone: %s", self._package)
            return "crash"
        if current is ForegroundState.BACKGROUNDED:
            self.bring_back()
            return "brought_back"
        return None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="foreground-watch",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_sec):
            if self.poll() is ForegroundState.CRASHED:
                return
