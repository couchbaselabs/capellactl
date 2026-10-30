"""Run-time context passed to reconcilers, the planner, the executor and the waiter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from capellactl.api.client import CapellaClient
from capellactl.engine.clock import Clock, get_clock


def _noop(*_msg: str) -> None:
    return None


@dataclass
class RunContext:
    client: CapellaClient
    config: Any = None
    clock: Clock = field(default_factory=get_clock)
    timeout: timedelta = timedelta(minutes=60)
    no_wait: bool = False
    progress: Callable[[str], None] = _noop
    # Optional: write without ending the line (a state line followed by a dot every 30s of waiting).
    progress_inline: Callable[..., None] | None = None  # (text, start=False): console.err_inline
    warn: Callable[[str, str], None] = _noop  # (what happened, what to do) (CAP-063)
    rotate_passwords: bool = False  # `apply --rotate-passwords` / `credential update --rotate-password` (CAP-028)
    power_on: bool = False  # `apply --power-on`: turn on a turned-off cluster before changing it (CAP-019 AC6)
    allow_service_removal: bool = False  # scale-in may remove the last nodes of a service (CAP-016 AC4)
    allow_service_group_removal: bool = False  # scale-in may remove a whole service group (CAP-016 AC4)
    skip_capacity_check: bool = False  # scale-in without the stats-based memory check (CAP-016 AC7)
