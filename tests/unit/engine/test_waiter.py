"""CAP-007: async operation waiter."""
from __future__ import annotations

from datetime import timedelta

import pytest

from capellactl.api.client import CapellaClient
from capellactl.engine.waiter import WaitFailed, poll_intervals, wait_for_cluster


@pytest.fixture
def client(fake, clock):
    return CapellaClient("k-123456", "org-1", clock=clock)


def _wait(client, clock, pid, cid, op, minutes=60):
    seen = []
    state = wait_for_cluster(client, pid, cid, op, timedelta(minutes=minutes), clock,
                             lambda s, e: seen.append((s, e)), name="nova-dev-01")
    return state, seen


@pytest.mark.story("CAP-007", "AC1")
def test_waiter_ac1_create_reaches_healthy(fake, client, clock):
    pid = fake.seed_project("p")
    cid = fake.seed_cluster(pid, "nova-dev-01")
    fake.set_transition(cid, ["deploying", "healthy"], step_seconds=240)
    state, seen = _wait(client, clock, pid, cid, "create")
    assert state == "healthy"
    assert seen[0] == ("deploying", 0)
    assert seen[-1][0] == "healthy" and seen[-1][1] >= 240


@pytest.mark.story("CAP-007", "AC1")
def test_waiter_ac1_prints_state_changes_only(fake, client, clock):
    pid = fake.seed_project("p")
    cid = fake.seed_cluster(pid, "nova-dev-01")
    fake.set_transition(cid, ["deploying", "healthy"], step_seconds=600)
    _, seen = _wait(client, clock, pid, cid, "create")
    assert [s for s, _ in seen] == ["deploying", "healthy"]


@pytest.mark.story("CAP-007", "AC2")
def test_waiter_ac2_backoff_sequence(fake, client, clock):
    assert poll_intervals()[:7] == [10, 15, 22.5, 33.75, 50.625, 60, 60]
    pid = fake.seed_project("p")
    cid = fake.seed_cluster(pid, "nova-dev-01")
    fake.set_transition(cid, ["deploying", "healthy"], step_seconds=600)
    _wait(client, clock, pid, cid, "create")
    assert clock.sleeps[:7] == [10, 15, 22.5, 33.75, 50.625, 60, 60]


@pytest.mark.story("CAP-007", "AC3")
@pytest.mark.parametrize("op,state", [("create", "deploymentFailed"), ("update", "scaleFailed"),
                                      ("update", "rebalanceFailed"), ("power_off", "turningOffFailed"),
                                      ("power_on", "turningOnFailed"), ("delete", "destroyFailed")])
def test_waiter_ac3_failure_states(fake, client, clock, op, state):
    pid = fake.seed_project("p")
    cid = fake.seed_cluster(pid, "nova-dev-01")
    fake.set_transition(cid, ["deploying", state], step_seconds=30)
    with pytest.raises(WaitFailed, match=f"cluster nova-dev-01 entered {state}; check the Capella UI activity log"):
        _wait(client, clock, pid, cid, op)


@pytest.mark.story("CAP-007", "AC7")
def test_waiter_ac7_delete_404_is_success(fake, client, clock):
    from capellactl.api import endpoints as ep

    pid = fake.seed_project("p")
    cid = fake.seed_cluster(pid, "nova-dev-01")
    ep.delete_cluster(client, pid, cid)
    state, _ = _wait(client, clock, pid, cid, "delete")
    assert state == "deleted"


@pytest.mark.story("CAP-007", "AC9")
def test_waiter_ac9_tick_every_30s_same_polls(fake, client, clock):
    pid = fake.seed_project("p")
    cid = fake.seed_cluster(pid, "nova-dev-01")
    fake.set_transition(cid, ["deploying", "healthy"], step_seconds=600)
    ticks: list[float] = []
    polls: list[float] = []

    def getter(c, p, i):
        polls.append(clock.monotonic())
        from capellactl.api import endpoints as ep
        return ep.get_cluster(c, p, i)

    wait_for_cluster(client, pid, cid, "create", timedelta(minutes=60), clock,
                     on_tick=lambda: ticks.append(clock.monotonic()), getter=getter)
    assert ticks[:4] == [30, 60, 90, 120]
    assert all(b - a == 30 for a, b in zip(ticks, ticks[1:], strict=False))
    assert ticks[-1] <= polls[-1]
    gaps = [b - a for a, b in zip(polls, polls[1:], strict=False)]
    assert gaps[:7] == [10, 15, 22.5, 33.75, 50.625, 60, 60]  # backoff unchanged by the ticks
