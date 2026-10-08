"""CAP-020: the hibernation schedule as code (plan and apply)."""
from __future__ import annotations

import pytest

from capellactl.resources.schedule import expand
from tests.conftest import MINIMAL, seed_healthy

HIB = {"timezone": "US/Pacific", "weekdays": "08:00-18:00", "weekend": "off", "friday": "08:00-14:30"}
WITH_HIB = MINIMAL + """\
    hibernation:
      timezone: US/Pacific
      weekdays: "08:00-18:00"
      weekend: "off"
      friday: "08:00-14:30"
"""
SCHED = "*/clusters/*/onOffSchedule"


def _sched_writes(fake):
    return [c for c in fake.writes() if "/onOffSchedule" in c.path]


@pytest.mark.story("CAP-020", "AC3")
def test_schedule_ac3_create_when_missing(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config(WITH_HIB)
    r = run("plan")
    assert "  + schedule nova-dev-01  US/Pacific · Mon–Thu 08:00–18:00 · Fri 08:00–14:30 · Sat–Sun off" in r.output
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    [post] = _sched_writes(fake)
    assert post.method == "POST" and post.body == expand(HIB)
    assert fake.schedules[cid]["activationStatus"] == "active"


@pytest.mark.story("CAP-020", "AC4")
def test_schedule_ac4_update_full_body_minimal_diff(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.schedules[cid] = {"activationStatus": "active", **expand({**HIB, "friday": "08:00-18:00"})}
    write_config(WITH_HIB)
    r = run("plan")
    assert "  ~ schedule nova-dev-01\n      friday:  \"08:00–18:00\" → \"08:00–14:30\"\n" in r.output, r.output
    fake.reset_calls()
    assert run("--auto-approve", "apply").exit_code == 0
    [put] = _sched_writes(fake)
    assert put.method == "PUT" and len(put.body["days"]) == 7 and put.headers.get("If-Match")
    assert put.body == expand(HIB)


@pytest.mark.story("CAP-020", "AC5")
def test_schedule_ac5_friendly_equals_api_noop(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.schedules[cid] = {"activationStatus": "active", **expand(HIB)}
    write_config(WITH_HIB)
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert "No changes" in r.output and fake.writes() == []


@pytest.mark.story("CAP-020", "AC6")
def test_schedule_ac6_omitted_untouched(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.schedules[cid] = {"activationStatus": "active", **expand(HIB)}
    write_config(MINIMAL)
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0 and fake.writes() == [] and cid in fake.schedules
    assert "schedule nova-dev-01  US/Pacific" in run("plan").output  # listed as unmanaged


@pytest.mark.story("CAP-020", "AC6")
def test_schedule_ac6_ensure_absent_deletes(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.schedules[cid] = {"activationStatus": "active", **expand(HIB)}
    write_config(MINIMAL + "    hibernation: { ensure: absent }\n")
    assert "  - schedule nova-dev-01" in run("plan").output
    fake.reset_calls()
    assert run("--auto-approve", "apply").exit_code == 0
    assert [(c.method, c.path.rsplit("/", 1)[1]) for c in _sched_writes(fake)] == [("DELETE", "onOffSchedule")]
    assert cid not in fake.schedules


@pytest.mark.story("CAP-020", "AC6")
def test_schedule_ac6_ensure_absent_when_none_noop(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL + "    hibernation: { ensure: absent }\n")
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output and fake.writes() == []


@pytest.mark.story("CAP-020", "AC8")
def test_schedule_ac8_update_while_turned_off(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["turnedOff"])
    fake.schedules[cid] = {"activationStatus": "active", **expand({**HIB, "friday": "08:00-18:00"})}
    write_config(WITH_HIB + """\
    buckets:
      - name: orders
        memoryAllocationInMb: 1024
""")
    r = run("plan")
    assert "~ schedule nova-dev-01" in r.output
    assert "! bucket nova-dev-01/orders" in r.output and "cluster is turned off" in r.output
    assert "(the schedule turns it on at Tue 08:00 US/Pacific)" in r.output  # now: Mon 10:00 PDT
    write_config(WITH_HIB)  # only the schedule changes: applied although the cluster is off
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert [c.method for c in _sched_writes(fake)] == ["PUT"]


@pytest.mark.story("CAP-020", "AC9")
def test_schedule_ac9_rerun_zero_writes(fake, run, write_config):
    seed_healthy(fake)
    write_config(WITH_HIB)
    assert run("--auto-approve", "apply").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert "No changes" in r.output and fake.writes() == []
