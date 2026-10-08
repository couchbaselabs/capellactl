"""CAP-021: pause and resume the hibernation schedule."""
from __future__ import annotations

import pytest

from capellactl.resources.schedule import expand
from tests.conftest import MINIMAL, file_clusters, seed_healthy

HIB = {"timezone": "US/Pacific", "weekdays": "08:00-18:00", "weekend": "off"}
WITH_HIB = MINIMAL + """\
    hibernation:
      timezone: US/Pacific
      weekdays: "08:00-18:00"
      weekend: "off"
"""


def _seed(fake, status="active", state="healthy"):
    _, cid = seed_healthy(fake)
    if state != "healthy":
        fake.set_transition(cid, [state])
    fake.schedules[cid] = {"activationStatus": status, **expand(HIB)}
    return cid


def _paths(fake):
    return [(c.method, c.path.split("/clusters/")[1].split("/", 1)[1]) for c in fake.writes()]


@pytest.mark.story("CAP-021", "AC1")
def test_schedule_pause_ac1_pause(fake, run, write_config):
    cid = _seed(fake, state="turnedOff")
    write_config(WITH_HIB)
    r = run("cluster", "schedule", "pause", "nova-dev-01")
    assert r.exit_code == 0, r.output
    assert "schedule paused; cluster will stay in its current state (off) until resumed" in r.output
    assert _paths(fake) == [("DELETE", "onOffSchedule/activationState")]
    assert fake.schedules[cid]["activationStatus"] == "paused"


@pytest.mark.story("CAP-021", "AC2")
def test_schedule_pause_ac2_resume_prints_next(fake, run, write_config):
    cid = _seed(fake, status="paused")
    write_config(WITH_HIB)
    r = run("cluster", "schedule", "resume", "nova-dev-01")  # now: Mon 10:00 US/Pacific
    assert r.exit_code == 0, r.output
    assert "schedule resumed; next: off at Mon 18:00 US/Pacific" in r.output
    assert _paths(fake) == [("POST", "onOffSchedule/activationState")]
    assert fake.schedules[cid]["activationStatus"] == "active"


@pytest.mark.story("CAP-021", "AC3")
@pytest.mark.parametrize(("status", "cmd", "message"), [("paused", "pause", "already paused"),
                                                       ("active", "resume", "already active")])
def test_schedule_pause_ac3_noop_when_already(fake, run, write_config, status, cmd, message):
    _seed(fake, status=status)
    write_config(WITH_HIB.replace('weekend: "off"\n', 'weekend: "off"\n      paused: true\n') if status == "paused"
                 else WITH_HIB)
    r = run("cluster", "schedule", cmd, "nova-dev-01")
    assert r.exit_code == 0 and message in r.output, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-021", "AC4")
def test_schedule_pause_ac4_no_schedule(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL)
    r = run("cluster", "schedule", "pause", "nova-dev-01")
    assert r.exit_code == 4 and "cluster nova-dev-01 has no on/off schedule" in r.output


@pytest.mark.story("CAP-021", "AC5")
def test_schedule_pause_ac5_power_on_order(fake, run, write_config):
    cid = _seed(fake, state="turnedOff")
    write_config(WITH_HIB)
    r = run("cluster", "schedule", "pause", "nova-dev-01", "--power-on")
    assert r.exit_code == 0, r.output
    assert _paths(fake) == [("DELETE", "onOffSchedule/activationState"), ("POST", "activationState")]
    assert fake.cluster_state(cid) == "healthy" and "cluster nova-dev-01 is on" in r.output


@pytest.mark.story("CAP-021", "AC6")
def test_schedule_pause_ac6_declarative_paused(fake, run, write_config):
    cid = _seed(fake)
    write_config(WITH_HIB.replace('weekend: "off"\n', 'weekend: "off"\n      paused: true\n'))
    r = run("plan")
    assert '  ~ schedule nova-dev-01\n      activationStatus:  "active" → "paused"' in r.output, r.output
    fake.reset_calls()
    assert run("--auto-approve", "apply").exit_code == 0
    assert _paths(fake) == [("DELETE", "onOffSchedule/activationState")]
    assert fake.schedules[cid]["activationStatus"] == "paused"
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output and fake.writes() == []


@pytest.mark.story("CAP-021", "AC6")
def test_schedule_pause_ac6_omitted_untouched(fake, run, write_config):
    cid = _seed(fake, status="paused")
    write_config(WITH_HIB)  # no paused key
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output and fake.writes() == []
    assert fake.schedules[cid]["activationStatus"] == "paused"


@pytest.mark.story("CAP-021", "AC6")
def test_schedule_pause_ac6_paused_after_create(fake, run, write_config):
    seed_healthy(fake)
    write_config(WITH_HIB.replace('weekend: "off"\n', 'weekend: "off"\n      paused: true\n'))
    assert run("--auto-approve", "apply").exit_code == 0
    assert _paths(fake) == [("POST", "onOffSchedule"), ("DELETE", "onOffSchedule/activationState")]


@pytest.mark.story("CAP-021", "AC7")
def test_schedule_pause_ac7_recorded_in_file(fake, run, write_config, tmp_path):
    """Revised: pause/resume record `paused` in capella.yaml, so the next apply does not undo them."""
    _seed(fake)
    write_config(WITH_HIB)
    r = run("cluster", "schedule", "pause", "nova-dev-01")
    assert "capella.yaml updated: paused: true for nova-dev-01" in r.output, r.output
    hib = file_clusters(tmp_path / "capella.yaml")[0]["hibernation"]
    assert hib["paused"] is True
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output and fake.writes() == []
    r = run("cluster", "schedule", "resume", "nova-dev-01")
    assert "capella.yaml updated: paused removed for nova-dev-01" in r.output
    assert "paused" not in (tmp_path / "capella.yaml").read_text()
