"""Foreground watchdog: classify package focus; gate applies actions."""

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
    ):
        self._adb = adb
        self._package = package
        self._poll_sec = poll_sec
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._state = ForegroundState.FOREGROUND
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> ForegroundState:
        with self._lock:
            return self._state

    def classify(self) -> ForegroundState:
        if not self._adb.is_package_running(self._package):
            return ForegroundState.CRASHED
        focused = self._adb.foreground_package()
        if not focused or focused == self._package:
            return ForegroundState.FOREGROUND
        return ForegroundState.BACKGROUNDED

    def poll(self) -> ForegroundState:
        state = self.classify()
        with self._lock:
            self._state = state
        return state

    def bring_back(self) -> None:
        print(f"foreground watch: bring back {self._package}", flush=True)
        _log.warning("package backgrounded; bringing to foreground %s", self._package)
        self._adb.bring_to_foreground(self._package)

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
