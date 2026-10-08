"""Wait for asynchronous cluster operations (CAP-007; 00-architecture.md section 8)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Literal

from capellactl.api import endpoints as ep
from capellactl.api.client import CapellaClient
from capellactl.api.errors import NotFound
from capellactl.engine.clock import Clock, format_duration

Op = Literal["create", "update", "power_off", "power_on", "delete", "ready"]

SUCCESS: dict[str, set[str]] = {
    "create": {"healthy"},
    "update": {"healthy"},
    "ready": {"healthy"},
    "power_off": {"turnedOff"},
    "power_on": {"healthy"},
    "delete": set(),  # success is a 404
}
FAILURE: dict[str, set[str]] = {
    "create": {"deploymentFailed"},
    "update": {"scaleFailed", "rebalanceFailed", "upgradeFailed"},
    "ready": {"deploymentFailed", "scaleFailed", "rebalanceFailed", "upgradeFailed", "destroyFailed",
              "turningOnFailed", "turningOffFailed", "peeringFailed"},
    "power_off": {"turningOffFailed"},
    "power_on": {"turningOnFailed"},
    "delete": {"destroyFailed"},
}
TRANSITIONAL = {"draft", "deploying", "scaling", "upgrading", "rebalancing", "peering", "destroying",
                "turningOff", "turningOn"}

FIRST_POLL = 10.0
POLL_FACTOR = 1.5
MAX_POLL = 60.0
TICK = 30.0  # on_tick is called every TICK seconds of waiting, between polls


class WaitFailed(Exception):
    def __init__(self, name: str, state: str) -> None:
        super().__init__(f"cluster {name} entered {state}; check the Capella UI activity log")
        self.state = state


class WaitTimeout(Exception):
    def __init__(self, name: str, state: str, timeout: timedelta) -> None:
        super().__init__(
            f"cluster {name} still {state} after {format_duration(timeout.total_seconds())}; "
            "the operation continues in Capella; re-run to resume waiting"
        )
        self.state = state


def poll_intervals() -> list[float]:
    """10, 15, 22.5, 33.75, 50.625, 60, 60, ... (first eight values, for tests and docs)."""
    out, v = [], FIRST_POLL
    for _ in range(8):
        out.append(min(v, MAX_POLL))
        v *= POLL_FACTOR
    return out


def wait_for_cluster(
    client: CapellaClient,
    project_id: str,
    cluster_id: str,
    op: Op,
    timeout: timedelta,
    clock: Clock,
    on_state: Callable[[str, float], None] | None = None,
    name: str | None = None,
    getter: Callable[[CapellaClient, str, str], tuple[dict[str, object], str | None]] | None = None,
    on_tick: Callable[[], None] | None = None,
) -> str:
    """Poll the cluster until the success state for `op`, a failure state, or the timeout.

    `on_tick` is called every TICK seconds while waiting (the CLI prints a dot), so a long wait never looks stuck.
    """
    label = name or cluster_id
    start = clock.monotonic()
    next_tick = TICK
    interval = FIRST_POLL
    last: str | None = None
    while True:
        try:
            body, _ = (getter or ep.get_cluster)(client, project_id, cluster_id)
        except NotFound:
            if op == "delete":
                if on_state:
                    on_state("deleted", clock.monotonic() - start)
                return "deleted"
            raise
        state = str(body.get("currentState", "unknown"))
        label = name or str(body.get("name") or cluster_id)
        elapsed = clock.monotonic() - start
        if state != last:
            if on_state:
                on_state(state, elapsed)
            last = state
        if state in SUCCESS[op]:
            return state
        if state in FAILURE[op]:
            raise WaitFailed(label, state)
        if elapsed >= timeout.total_seconds():
            raise WaitTimeout(label, state, timeout)
        sleep_for = min(interval, MAX_POLL, max(0.0, timeout.total_seconds() - elapsed) or interval)
        wake = elapsed + sleep_for
        while on_tick and next_tick <= wake:  # sleep in slices so a tick lands every TICK seconds
            clock.sleep(next_tick - (clock.monotonic() - start))
            on_tick()
            next_tick += TICK
        rest = wake - (clock.monotonic() - start)
        if rest > 0:
            clock.sleep(rest)
        interval = min(interval * POLL_FACTOR, MAX_POLL)
