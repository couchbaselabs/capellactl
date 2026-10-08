"""CAP-007: waiting from the CLI."""
from __future__ import annotations

import pytest

from tests.conftest import MINIMAL, seed_healthy
from tests.scenario.helpers import FULL


@pytest.mark.story("CAP-007", "AC1")
def test_waiter_ac1_progress_lines(fake, run, write_config):
    write_config()
    r = run("--auto-approve", "apply")
    assert "  cluster nova-dev-01: deploying (0s)" in r.output
    assert "  cluster nova-dev-01: healthy (1m21s)" in r.output


@pytest.mark.story("CAP-007", "AC4")
def test_waiter_ac4_timeout_exit_5(fake, run, write_config):
    seed_healthy(fake)
    fake.step_seconds = 3600
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4"))
    r = run("--auto-approve", "--timeout", "5m", "apply")
    assert r.exit_code == 5
    assert "still scaling after 5m0s; the operation continues in Capella; re-run to resume waiting" in r.output


@pytest.mark.story("CAP-007", "AC5")
def test_waiter_ac5_no_wait_defers_children(fake, run, write_config, stub_tree):
    write_config(FULL)
    r = run("--auto-approve", "--no-wait", "apply")
    assert r.exit_code == 0, r.output
    assert [c.path.split("/")[-1] for c in fake.writes()] == ["projects", "clusters"]
    assert "deferred" in r.output


@pytest.mark.story("CAP-007", "AC5")
def test_waiter_ac5_later_apply_completes(fake, run, write_config, stub_tree):
    write_config(FULL)
    run("--auto-approve", "--no-wait", "apply")
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "cluster nova-dev-01: deploying" in r.output and "cluster nova-dev-01: healthy" in r.output
    assert not fake.calls("POST", "*/clusters")
    assert fake.calls("POST", "*/users")


@pytest.mark.story("CAP-007", "AC6")
def test_waiter_ac6_transitional_state_no_second_write(fake, run, write_config):
    _, cid = seed_healthy(fake, nodes=4)
    fake.set_transition(cid, ["scaling", "healthy"])
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-007", "AC6")
def test_waiter_ac6_update_waits_until_healthy_first(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["rebalancing", "healthy"])
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 5"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    put = fake.calls("PUT", "*/clusters/*")[0]
    gets_before = [c for c in fake.calls("GET", f"*/clusters/{cid}") if fake._calls.index(c) < fake._calls.index(put)]
    assert gets_before, "must poll before sending the update"
    assert "cluster nova-dev-01: rebalancing" in r.output


@pytest.mark.story("CAP-007", "AC8")
def test_waiter_ac8_interrupt_message(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4"))
    put_done: list[bool] = []

    def interrupt_while_waiting(method: str, path: str) -> None:
        if method == "PUT":
            put_done.append(True)
        elif put_done and method == "GET" and "/clusters/c-" in path:
            raise KeyboardInterrupt()

    fake.hooks.append(interrupt_while_waiting)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 130
    assert "stopped waiting; the operation continues in Capella" in r.output


@pytest.mark.story("CAP-007", "AC9")
def test_waiter_ac9_dots_and_total_time(fake, run, write_config):
    write_config()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "  cluster nova-dev-01: deploying (0s) ..\n  cluster nova-dev-01: healthy (1m21s)\n" in r.output
    assert "  done cluster nova-dev-01 in 1m21s" in r.output
    assert "Apply complete in 1m21s." in r.output


@pytest.mark.story("CAP-007", "AC9")
def test_waiter_ac9_delete_dots_and_total_time(fake, run):
    seed_healthy(fake)
    assert run("import").exit_code == 0
    fake.step_seconds = 200
    r = run("--auto-approve", "cluster", "delete", "nova-dev-01")
    assert r.exit_code == 0, r.output
    assert "  cluster nova-dev-01: destroying (0s) ........\n  cluster nova-dev-01: deleted (4m12s)\n" in r.output
