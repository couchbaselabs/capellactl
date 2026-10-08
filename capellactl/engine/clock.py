"""Clock abstraction so waits and retries can run on a fake clock in tests."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def now(self) -> datetime: ...
    def sleep(self, seconds: float) -> None: ...


class RealClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FakeClock:
    """Deterministic clock: sleep() advances time instantly."""

    def __init__(self, start: datetime | None = None) -> None:
        self._t = 0.0
        self._start = start or datetime(2026, 10, 5, 17, 0, tzinfo=timezone.utc)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._t

    def now(self) -> datetime:
        from datetime import timedelta

        return self._start + timedelta(seconds=self._t)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._t += seconds

    def advance(self, seconds: float) -> None:
        self._t += seconds


_default: Clock = RealClock()


def get_clock() -> Clock:
    return _default


def set_clock(clock: Clock) -> None:
    global _default
    _default = clock


def format_duration(seconds: float) -> str:
    """4m0s, 1h2m3s, 12s, 1.2s."""
    if seconds < 10 and seconds != int(seconds):
        return f"{seconds:.1f}s"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m}m{sec}s"
    if m:
        return f"{m}m{sec}s"
    return f"{sec}s"
