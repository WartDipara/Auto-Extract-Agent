from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from shared.prep.adb_device import AdbDevice

_log = logging.getLogger(__name__)


class AdbPool:
    """One lock per online serial. Never nest with OpenCodePool."""

    def __init__(self, *, wait_timeout_sec: float = 3600.0):
        self._wait_timeout_sec = float(wait_timeout_sec)
        self._cond = threading.Condition()
        self._locks: dict[str, threading.Lock] = {}
        self._held: set[str] = set()

    def refresh(self) -> list[str]:
        devices = AdbDevice().list_online_devices()
        with self._cond:
            for serial in devices:
                self._locks.setdefault(serial, threading.Lock())
            gone = [s for s in self._locks if s not in devices and s not in self._held]
            for s in gone:
                self._locks.pop(s, None)
            self._cond.notify_all()
        return devices

    def acquire(self, preferred: str | None = None) -> str:
        deadline = time.monotonic() + self._wait_timeout_sec
        preferred = (preferred or "").strip()
        while True:
            self.refresh()
            with self._cond:
                candidates = (
                    [preferred]
                    if preferred and preferred in self._locks
                    else sorted(self._locks)
                )
                for serial in candidates:
                    lock = self._locks.get(serial)
                    if lock is None:
                        continue
                    if lock.acquire(blocking=False):
                        self._held.add(serial)
                        _log.info("adb acquired %s", serial)
                        return serial
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("DEVICE_WAIT_TIMEOUT")
                self._cond.wait(timeout=min(2.0, remaining))

    def release(self, serial: str) -> None:
        serial = (serial or "").strip()
        if not serial:
            return
        with self._cond:
            lock = self._locks.get(serial)
            if lock is None:
                self._held.discard(serial)
                return
            if serial in self._held:
                try:
                    lock.release()
                except RuntimeError:
                    pass
                self._held.discard(serial)
                _log.info("adb released %s", serial)
            self._cond.notify_all()

    @contextmanager
    def hold(self, preferred: str | None = None) -> Iterator[str]:
        serial = self.acquire(preferred)
        try:
            yield serial
        finally:
            self.release(serial)


class OpenCodePool:
    def __init__(self, slots: int = 1, *, wait_timeout_sec: float = 7200.0):
        self._sem = threading.Semaphore(max(1, int(slots)))
        self._wait_timeout_sec = float(wait_timeout_sec)

    def acquire(self) -> None:
        ok = self._sem.acquire(timeout=self._wait_timeout_sec)
        if not ok:
            raise TimeoutError("OPENCODE_WAIT_TIMEOUT")
        _log.info("opencode slot acquired")

    def release(self) -> None:
        self._sem.release()
        _log.info("opencode slot released")

    @contextmanager
    def hold(self) -> Iterator[None]:
        self.acquire()
        try:
            yield
        finally:
            self.release()
