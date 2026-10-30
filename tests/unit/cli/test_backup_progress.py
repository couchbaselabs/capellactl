"""CAP-057 AC8, CAP-059 AC8: backup, restore and export waits show progress like a cluster wait."""
from __future__ import annotations

from datetime import timedelta

import pytest

from capellactl.cli.backup_common import DONE, FAILED, progress
from capellactl.engine.waiter import wait_for_status


def _run(clock, statuses: list[tuple[float, str]]) -> list[float]:
    """Wait on a status that changes at the given seconds; returns when the ticks landed."""
    start = clock.monotonic()
    ticks: list[float] = []
    shown = progress("backup of orders")

    def read() -> str:
        elapsed = clock.monotonic() - start
        return [s for t, s in statuses if t <= elapsed][-1]

    def on_tick() -> None:
        ticks.append(clock.monotonic() - start)
        shown["on_tick"]()

    wait_for_status(read, DONE, FAILED, timedelta(minutes=60), clock, "backup of orders", shown["on_state"], on_tick)
    return ticks


@pytest.mark.story("CAP-057", "AC8")
def test_backup_progress_ac8_dots_every_30s_on_one_line(clock, capsys):
    ticks = _run(clock, [(0, "queued"), (20, "running"), (100, "complete")])
    assert ticks == [30, 60, 90, 120]
    err = capsys.readouterr().err
    assert err.splitlines() == [
        "  backup of orders: queued (0s) ",
        "  backup of orders: running (25s) ....",
        "  backup of orders: complete (2m12s)",
    ], err


@pytest.mark.story("CAP-059", "AC8")
def test_backup_progress_ac8_failed_ends_the_line(clock, capsys):
    from capellactl.engine.waiter import StatusFailed

    with pytest.raises(StatusFailed):
        _run(clock, [(0, "pending"), (40, "failed")])
    lines = capsys.readouterr().err.splitlines()
    assert lines[0].startswith("  backup of orders: pending (0s) .") and lines[1].startswith(
        "  backup of orders: failed (")


@pytest.mark.story("CAP-007", "AC9")
def test_waiter_ac9_each_state_on_its_own_line(capsys):
    """Two in-progress states in a row (deploying, then rebalancing) each start a line; dots continue the open one."""
    from capellactl.cli.console import wait_progress

    on_state, on_tick = wait_progress("cluster nova-dev-01")
    on_state("deploying", 0)
    on_tick()
    on_state("rebalancing", 400)
    on_tick()
    on_state("healthy", 700)
    assert capsys.readouterr().err.splitlines() == [
        "  cluster nova-dev-01: deploying (0s) .",
        "  cluster nova-dev-01: rebalancing (6m40s) .",
        "  cluster nova-dev-01: healthy (11m40s)",
    ]
