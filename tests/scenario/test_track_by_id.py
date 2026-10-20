"""CAP-048: projects and clusters are tracked by id, so a rename in the Capella UI is never a new resource."""
from __future__ import annotations

import pytest
import yaml

from tests.conftest import MINIMAL, seed_healthy


@pytest.fixture
def imported(fake, run, tmp_path):
    pid, cid = seed_healthy(fake)
    assert run("import").exit_code == 0
    fake.reset_calls()
    return pid, cid, tmp_path / "capella.yaml"


def _rename(fake, pid, name="nova-dev-renamed"):
    fake.projects[pid]["name"] = name


@pytest.mark.story("CAP-048", "AC1")
def test_track_by_id_ac1_import_pins_ids(fake, run, imported):
    pid, cid, path = imported
    proj = yaml.safe_load(path.read_text(encoding="utf-8"))["projects"][0]
    assert proj["id"] == pid and proj["clusters"][0]["id"] == cid
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0, r.output


@pytest.mark.story("CAP-048", "AC2")
def test_track_by_id_ac2_pinned_rename_shown_as_rename(fake, run, imported):
    pid, _, _ = imported
    _rename(fake, pid)
    r = run("plan")
    assert r.exit_code == 0, r.output
    assert "~ project nova-dev" in r.output
    assert 'name:  "nova-dev-renamed" → "nova-dev"' in r.output
    assert "'capellactl sync' keeps the new name" in r.output
    assert "  + " not in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-048", "AC3")
def test_track_by_id_ac3_sync_adopts_new_name(fake, run, imported):
    pid, _, path = imported
    _rename(fake, pid)
    r = run("sync")
    assert r.exit_code == 0, r.output
    proj = yaml.safe_load(path.read_text(encoding="utf-8"))["projects"][0]
    assert (proj["id"], proj["name"]) == (pid, "nova-dev-renamed")
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-048", "AC4")
def test_track_by_id_ac4_unpinned_rename_blocks_create(fake, run, write_config):
    pid, _ = seed_healthy(fake)
    write_config()  # no ids
    _rename(fake, pid)
    r = run("plan")
    assert "project nova-dev-renamed has its cluster nova-dev-01" in r.output
    assert "capellactl sync" in r.output and "+ project nova-dev" not in r.output
    assert "+ cluster" not in r.output and "0 to add" in r.output and "1 blocked" in r.output
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-048", "AC4")
def test_track_by_id_ac4_new_project_still_created(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL.replace("name: nova-dev\n", "name: nova-qa\n", 1).replace("nova-dev-01", "nova-qa-01"))
    r = run("plan")
    assert r.exit_code == 0, r.output
    assert "+ project nova-qa" in r.output and "renamed" not in r.output


@pytest.mark.story("CAP-048", "AC5")
def test_track_by_id_ac5_sync_adopts_unpinned_rename(fake, run, write_config, tmp_path):
    pid, cid = seed_healthy(fake)
    write_config()
    _rename(fake, pid)
    r = run("sync")
    assert r.exit_code == 0, r.output
    assert "project nova-dev was renamed in Capella to nova-dev-renamed" in r.output
    proj = yaml.safe_load((tmp_path / "capella.yaml").read_text(encoding="utf-8"))["projects"][0]
    assert (proj["id"], proj["name"], proj["clusters"][0]["id"]) == (pid, "nova-dev-renamed", cid)
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0, r.output
