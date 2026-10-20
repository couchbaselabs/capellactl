"""CAP-020 AC7: cluster schedule show; and the schedule commands that record in capella.yaml."""
from __future__ import annotations

import json

import pytest
import yaml

from capellactl.resources.schedule import expand
from tests.conftest import seed_healthy

HIB = {"timezone": "US/Pacific", "weekdays": "08:00-18:00", "weekend": "off", "friday": "08:00-14:30"}


@pytest.mark.story("CAP-020", "AC7")
def test_schedule_show_ac7_grid_and_next(fake, run, clock):
    _, cid = seed_healthy(fake)
    fake.schedules[cid] = {"activationStatus": "active", **expand(HIB)}
    assert run("import").exit_code == 0
    clock.advance(4 * 86400 + 3 * 3600)  # Mon 17:00 UTC → Fri 20:00 UTC = Fri 13:00 US/Pacific
    r = run("cluster", "schedule", "show", "nova-dev-01")
    assert r.exit_code == 0, r.output
    assert "nova-dev-01  US/Pacific  active" in r.output
    assert "Mon " + "░" * 8 + "█" * 10 + "░" * 6 + "  08:00–18:00" in r.output
    assert "Fri " + "░" * 8 + "█" * 7 + "░" * 9 + "  08:00–14:30" in r.output  # 14:00–14:30 is on
    assert "Sat " + "░" * 24 + "  off" in r.output
    assert "Next: off at Fri 14:30 US/Pacific" in r.output
    js = json.loads(run("-o", "json", "cluster", "schedule", "show", "nova-dev-01").output)
    assert js["nextTransition"] == {"state": "off", "at": "2026-10-09T14:30:00-07:00"}


@pytest.mark.story("CAP-020", "AC3")
def test_schedule_set_ac3_records_and_creates(fake, run, tmp_path):
    _, cid = seed_healthy(fake)
    assert run("import").exit_code == 0
    r = run("--auto-approve", "cluster", "schedule", "set", "nova-dev-01", "--timezone", "US/Pacific",
            "--weekdays", "08:00-18:00", "--weekend", "off", "--friday", "08:00-14:30")
    assert r.exit_code == 0, r.output
    assert "+ schedule nova-dev-01  US/Pacific · Mon–Thu 08:00–18:00 · Fri 08:00–14:30 · Sat–Sun off" in r.output
    assert fake.schedules[cid]["days"] == expand(HIB)["days"]
    hib = yaml.safe_load((tmp_path / "capella.yaml").read_text(encoding="utf-8"))["projects"][0]["clusters"][0]["hibernation"]
    assert hib == HIB
    assert "already in sync" in run("sync").output
    r = run("--auto-approve", "cluster", "schedule", "set", "nova-dev-01", "--friday", "08:00-18:00")
    assert r.exit_code == 0 and 'friday:  "08:00–14:30" → "08:00–18:00"' in r.output, r.output


@pytest.mark.story("CAP-020", "AC6")
def test_schedule_delete_ac6_removes_from_capella_and_file(fake, run, tmp_path):
    _, cid = seed_healthy(fake)
    fake.schedules[cid] = {"activationStatus": "active", **expand(HIB)}
    assert run("import").exit_code == 0
    assert "hibernation" in (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "schedule", "delete", "nova-dev-01")
    assert r.exit_code == 0 and "deleted the on/off schedule of nova-dev-01" in r.output, r.output
    assert cid not in fake.schedules and "hibernation" not in (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert "already in sync" in run("sync").output
