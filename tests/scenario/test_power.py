"""CAP-019: power a cluster off and on."""
from __future__ import annotations

import pytest

from capellactl.cli import console
from capellactl.resources.schedule import expand
from tests.conftest import MINIMAL, seed_healthy

ACT = "*/clusters/*/activationState"


@pytest.mark.story("CAP-019", "AC1")
def test_power_ac1_off_and_wait(fake, run, write_config, monkeypatch):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL)
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "power", "nova-dev-01", "--off", input="y\n")
    assert r.exit_code == 0, r.output
    assert "storage remains" in r.output and "Charges for the Data API continue" in r.output
    assert "cluster nova-dev-01: turningOff" in r.output
    assert "cluster nova-dev-01 is off (storage, data and configuration retained)" in r.output
    assert [c.method for c in fake.calls(path_glob=ACT)] == ["DELETE"]
    assert fake.cluster_state(cid) == "turnedOff"


@pytest.mark.story("CAP-019", "AC2")
@pytest.mark.parametrize(("flags", "linked"), [((), False), (("--with-app-service",), True)])
def test_power_ac2_on_body_flag(fake, run, write_config, flags, linked):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["turnedOff"])
    write_config(MINIMAL)
    r = run("cluster", "power", "nova-dev-01", "--on", *flags)
    assert r.exit_code == 0 and "cluster nova-dev-01 is on" in r.output, r.output
    [post] = fake.calls("POST", ACT)
    assert post.body == {"turnOnLinkedAppService": linked}
    assert fake.cluster_state(cid) == "healthy"


@pytest.mark.story("CAP-019", "AC3")
@pytest.mark.parametrize(("state", "flag", "word"), [("turnedOff", "--off", "off"), ("healthy", "--on", "on")])
def test_power_ac3_already_in_state_noop(fake, run, write_config, state, flag, word):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, [state])
    write_config(MINIMAL)
    r = run("cluster", "power", "nova-dev-01", flag)
    assert r.exit_code == 0 and f"already {word}" in r.output, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-019", "AC4")
def test_power_ac4_same_direction_waits_only(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["turningOff", "turnedOff"])
    write_config(MINIMAL)
    r = run("--auto-approve", "cluster", "power", "nova-dev-01", "--off")
    assert r.exit_code == 0 and "cluster nova-dev-01 is off" in r.output, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-019", "AC4")
def test_power_ac4_opposite_direction_waits_then_acts(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["turningOff", "turnedOff"])
    write_config(MINIMAL)
    r = run("cluster", "power", "nova-dev-01", "--on")
    assert r.exit_code == 0, r.output
    assert r.output.index("turningOff") < r.output.index("turningOn")
    assert [c.method for c in fake.calls(path_glob=ACT)] == ["POST"]
    assert fake.cluster_state(cid) == "healthy"


@pytest.mark.story("CAP-019", "AC5")
def test_power_ac5_409_rereads_state(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["turnedOff"])
    write_config(MINIMAL)
    fake.fail_next("POST", ACT, 409, 1010)
    r = run("cluster", "power", "nova-dev-01", "--on")
    assert r.exit_code == 0, r.output
    assert len(fake.calls("POST", ACT)) == 2 and fake.cluster_state(cid) == "healthy"
    fake.set_transition(cid, ["turnedOff"])
    fake.fail_next("POST", ACT, 409, 1010, times=2)
    r = run("cluster", "power", "nova-dev-01", "--on")
    assert r.exit_code == 1 and "Capella refused" in r.output and "injected 409" in r.output


@pytest.mark.story("CAP-019", "AC5")
def test_power_ac5_turning_on_failed(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["turningOn", "turningOnFailed"])
    write_config(MINIMAL)
    r = run("cluster", "power", "nova-dev-01", "--on")
    assert r.exit_code == 1 and "entered turningOnFailed; check the Capella UI activity log" in r.output


@pytest.mark.story("CAP-019", "AC6")
def test_power_ac6_apply_turned_off_blocked(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["turnedOff"])
    write_config(MINIMAL + "    buckets:\n      - name: orders\n        memoryAllocationInMb: 1024\n")
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4, r.output
    assert "! bucket nova-dev-01/orders  cluster is turned off; run 'capellactl cluster power nova-dev-01 --on' " \
           "or pass --power-on" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-019", "AC6")
def test_power_ac6_apply_power_on_flag(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["turnedOff"])
    write_config(MINIMAL + "    buckets:\n      - name: orders\n        memoryAllocationInMb: 1024\n")
    r = run("plan")
    assert "! bucket" in r.output
    r = run("--auto-approve", "apply", "--power-on")
    assert r.exit_code == 0, r.output
    assert "~ cluster nova-dev-01   power on" in r.output
    writes = [(c.method, c.path.rsplit("/", 1)[1]) for c in fake.writes()]
    assert writes == [("POST", "activationState"), ("POST", "buckets")]
    assert fake.cluster_state(cid) == "healthy"


@pytest.mark.story("CAP-019", "AC7")
def test_power_ac7_schedule_next_on_note(fake, run, write_config, clock):
    _, cid = seed_healthy(fake)
    fake.schedules[cid] = {"activationStatus": "active", **expand(
        {"timezone": "US/Pacific", "weekdays": "08:00-18:00", "weekend": "off"})}
    write_config(MINIMAL)
    clock.advance(4 * 86400 + 9 * 3600)  # Mon 17:00 UTC → Sat 02:00 UTC = Fri 19:00 US/Pacific
    r = run("--auto-approve", "cluster", "power", "nova-dev-01", "--off")
    assert r.exit_code == 0, r.output
    assert "note: the on/off schedule will turn this cluster on at Mon 08:00 US/Pacific" in r.output


@pytest.mark.story("CAP-019", "AC8")
def test_power_ac8_rerun_zero_writes(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL)
    assert run("--auto-approve", "cluster", "power", "nova-dev-01", "--off").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "power", "nova-dev-01", "--off")
    assert r.exit_code == 0 and "already off" in r.output and fake.writes() == []


@pytest.mark.story("CAP-019", "AC9")
def test_power_ac9_free_tier_endpoints(fake, run, tmp_path):
    pid = fake.seed_project("nova-dev")
    cid = fake.seed_free_cluster(pid, "try-01")
    assert run("import").exit_code == 0
    r = run("--auto-approve", "cluster", "power", "try-01", "--off")
    assert r.exit_code == 0 and "cluster try-01 is off" in r.output, r.output
    r = run("cluster", "power", "try-01", "--on")
    assert r.exit_code == 0 and "cluster try-01 is on" in r.output, r.output
    assert [(c.method, c.path.split("/clusters/")[1]) for c in fake.writes()] == [
        ("DELETE", f"freeTier/{cid}/activationState"), ("POST", f"freeTier/{cid}/activationState")]
