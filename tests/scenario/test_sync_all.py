"""CAP-054: one command (`sync`) brings capella.yaml in line with every project of the organization."""
from __future__ import annotations

import pytest
import yaml

from tests.conftest import file_clusters, file_projects, seed_healthy


def _non_prod(fake, off: int = 0):
    """Project non-prod with three clusters; the first `off` of them turned off."""
    pid = fake.seed_project("non-prod")
    ids = []
    for i, name in enumerate(("np-01", "np-02", "np-03")):
        cid = fake.seed_cluster(pid, name, cloudProvider={"type": "azure", "region": "eastus",
                                                          "cidr": f"10.30.{i}.0/24"})
        fake.seed_bucket(cid, "orders", memoryAllocationInMb=512)
        if i < off:
            fake.set_transition(cid, ["turnedOff"])
        ids.append(cid)
    return pid, ids


@pytest.fixture
def one_project_file(fake, run, tmp_path):
    seed_healthy(fake)
    assert run("sync", "--project", "nova-dev").exit_code == 0
    fake.reset_calls()
    return tmp_path / "capella.yaml"


@pytest.mark.story("CAP-054", "AC1")
def test_sync_all_ac1_adds_missing_projects(fake, run, one_project_file):
    _non_prod(fake)
    r = run("sync")
    assert r.exit_code == 0, r.output
    assert "added project non-prod (3 clusters)" in r.output
    assert [p["name"] for p in file_projects(one_project_file)] == ["nova-dev", "non-prod"]
    assert [c["name"] for c in file_clusters(one_project_file, "non-prod")] == ["np-01", "np-02", "np-03"]
    r = run("sync")
    assert "capella.yaml is already in sync with Capella: 2 projects, 4 clusters." in r.output


@pytest.mark.story("CAP-054", "AC1")
def test_sync_all_ac1_dry_run_flags_missing_project(fake, run, one_project_file):
    _non_prod(fake)
    before = one_project_file.read_text(encoding="utf-8")
    r = run("sync", "--dry-run")
    assert r.exit_code == 2, r.output
    assert "+  name: non-prod" in r.output
    assert one_project_file.read_text(encoding="utf-8") == before


@pytest.mark.story("CAP-054", "AC2")
def test_sync_all_ac2_creates_file_like_import(fake, run, tmp_path):
    seed_healthy(fake)
    _non_prod(fake)
    path = tmp_path / "capella.yaml"
    r = run("sync")
    assert r.exit_code == 0, r.output
    created = yaml.safe_load(path.read_text(encoding="utf-8"))
    path.unlink()
    assert run("import").exit_code == 0
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == created
    assert [p["name"] for p in created["projects"]] == ["nova-dev", "non-prod"]


@pytest.mark.story("CAP-054", "AC2")
def test_sync_all_ac2_stdout(fake, run, tmp_path):
    seed_healthy(fake)
    r = run("sync", "--stdout")
    assert r.exit_code == 0, r.output
    assert "name: nova-dev-01" in r.output and not (tmp_path / "capella.yaml").exists()
    r = run("sync", "--dry-run")
    assert r.exit_code == 2 and "does not exist yet" in r.output


@pytest.mark.story("CAP-054", "AC3")
def test_sync_all_ac3_project_limits_run(fake, run, one_project_file):
    non_prod, _ = _non_prod(fake)
    fake.reset_calls()
    r = run("sync", "--project", "nova-dev")
    assert r.exit_code == 0, r.output
    assert "already in sync with Capella for nova-dev (other projects not checked)" in r.output
    assert fake.calls("GET", f"*/projects/{non_prod}/clusters") == []
    assert [p["name"] for p in file_projects(one_project_file)] == ["nova-dev"]
    r = run("sync", "--project", "non-prod")
    assert "added project non-prod (3 clusters)" in r.output


@pytest.mark.story("CAP-054", "AC3")
def test_sync_all_ac3_skip_project_remembered(fake, run, one_project_file):
    _non_prod(fake)
    assert run("sync").exit_code == 0
    r = run("sync", "--skip-project", "non-prod")
    assert r.exit_code == 0, r.output
    assert "project non-prod removed from capella.yaml and skipped from now on" in r.output
    data = yaml.safe_load(one_project_file.read_text(encoding="utf-8"))
    assert data["skipProjects"] == ["non-prod"] and [p["name"] for p in data["projects"]] == ["nova-dev"]
    assert run("validate").exit_code == 0
    r = run("sync")
    assert "added project" not in r.output and "skipped: non-prod" in r.output
    r = run("sync", "--project", "non-prod")
    assert "added project non-prod" in r.output
    data = yaml.safe_load(one_project_file.read_text(encoding="utf-8"))
    assert "skipProjects" not in data and [p["name"] for p in data["projects"]] == ["nova-dev", "non-prod"]


@pytest.mark.story("CAP-054", "AC3")
def test_sync_all_ac3_skip_on_first_sync(fake, run, tmp_path):
    seed_healthy(fake)
    _non_prod(fake)
    assert run("sync", "--skip-project", "non-prod").exit_code == 0
    data = yaml.safe_load((tmp_path / "capella.yaml").read_text(encoding="utf-8"))
    assert data["skipProjects"] == ["non-prod"] and [p["name"] for p in data["projects"]] == ["nova-dev"]
    assert "added project" not in run("sync").output


@pytest.mark.story("CAP-054", "AC4")
def test_sync_all_ac4_turned_off_not_waited_for(fake, run, one_project_file, clock):
    _, ids = _non_prod(fake, off=2)
    fake.reset_calls()
    start = clock.monotonic()
    r = run("sync")
    assert r.exit_code == 0, r.output
    assert clock.monotonic() == start  # nothing waited
    for cid in ids[:2]:
        assert not fake.calls("GET", f"*/clusters/{cid}/buckets") and not fake.calls("GET", f"*/clusters/{cid}/users")
    assert "2 clusters are turned off: np-01, np-02" in r.output
    assert "not read yet: buckets and credentials of np-01, np-02 — run 'capellactl sync' again when they are on" \
        in r.output
    clusters = {c["name"]: c for c in file_clusters(one_project_file, "non-prod")}
    assert clusters["np-01"]["serviceGroups"] and "buckets" not in clusters["np-01"]
    assert clusters["np-03"]["buckets"][0]["name"] == "orders"


@pytest.mark.story("CAP-054", "AC4")
def test_sync_all_ac4_picked_up_when_on(fake, run, one_project_file):
    _, ids = _non_prod(fake, off=2)
    assert run("sync").exit_code == 0
    fake.set_transition(ids[0], ["healthy"])
    r = run("sync")
    assert r.exit_code == 0, r.output
    assert "1 cluster is turned off: np-02" in r.output
    clusters = {c["name"]: c for c in file_clusters(one_project_file, "non-prod")}
    assert clusters["np-01"]["buckets"][0]["name"] == "orders" and "buckets" not in clusters["np-02"]
    fake.set_transition(ids[2], ["turnedOff"])  # recorded with buckets, then turned off: kept (CAP-038 AC14)
    r = run("sync")
    assert "kept from capella.yaml: buckets and credentials of np-03" in r.output
    clusters = {c["name"]: c for c in file_clusters(one_project_file, "non-prod")}
    assert clusters["np-03"]["buckets"][0]["name"] == "orders"


@pytest.mark.story("CAP-054", "AC5")
@pytest.mark.parametrize("args", [(), ("--project", "nova-dev"), ("--project", "nova-dev", "--cluster", "nova-dev-01"),
                                  ("--full",)])
def test_sync_all_ac5_import_alias(fake, run, tmp_path, args):
    seed_healthy(fake)
    path = tmp_path / "capella.yaml"
    r = run("import", *args)
    assert r.exit_code == 0, r.output
    assert "note: 'import' is now 'sync'" in r.output
    via_import = yaml.safe_load(path.read_text(encoding="utf-8"))
    path.unlink()
    assert run("sync", *args).exit_code == 0
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == via_import
    other = tmp_path / "other.yaml"
    assert run("import", "--file", str(other)).exit_code == 0 and other.exists()
    r = run("import", "--stdout")
    assert "name: nova-dev-01" in r.output and "note:" not in r.output
    assert "sync" in run("import", "--help").output


@pytest.mark.story("CAP-054", "AC6")
def test_sync_all_ac6_only_gets_and_no_rewrite(fake, run, one_project_file):
    _non_prod(fake, off=1)
    assert run("sync").exit_code == 0
    assert fake.writes() == []
    backup = one_project_file.with_name("capella.yaml.bak")
    backup.unlink()
    text = one_project_file.read_text(encoding="utf-8")
    r = run("sync")
    assert "already in sync" in r.output
    assert one_project_file.read_text(encoding="utf-8") == text and not backup.exists()
    assert fake.writes() == []
