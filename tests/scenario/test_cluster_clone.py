"""CAP-049: clone a cluster into another region."""
from __future__ import annotations

import json

import pytest
import yaml

from capellactl.cli import console
from tests.conftest import file_clusters
from tests.scenario.helpers import seed_user

AZURE_GROUPS = [{"node": {"compute": {"cpu": 8, "ram": 32}, "disk": {"type": "P10", "storage": 128, "iops": 500}},
                 "numOfNodes": 3,
                 "services": ["data", "index", "query"]}]
CLUSTERS = "/v4/organizations/org-1/projects/{pid}/clusters"


@pytest.fixture
def demo(fake, run, tmp_path):
    """Project nova-demo with azure cluster nova-demo-01 in eastus (bucket demo, scope inventory, two collections,
    an allowed CIDR and a credential), imported into capella.yaml."""
    pid = fake.seed_project("nova-demo")
    cid = fake.seed_cluster(pid, "nova-demo-01", description="Demo", serviceGroups=AZURE_GROUPS,
                            cloudProvider={"type": "azure", "region": "eastus", "cidr": "10.0.0.0/24"},
                            support={"plan": "enterprise", "timezone": "ET"}, zones=["1", "2", "3"],
                            couchbaseServer={"version": "7.6.2"})
    fake.seed_bucket(cid, "demo", memoryAllocationInMb=512)
    fake.seed_scope(cid, "demo", "inventory", {"airline": 0, "route": 3600})
    fake.cidrs["cidr-1"] = {"id": "cidr-1", "_cluster": cid, "cidr": "203.0.113.10/32", "status": "active",
                            "comment": "Office"}
    seed_user(fake, cid, "demo_app", [{"privileges": ["data_reader", "data_writer"],
                                       "resources": {"buckets": [{"name": "demo"}]}}])
    assert run("import").exit_code == 0
    fake.reset_calls()
    return {"pid": pid, "cid": cid, "file": tmp_path / "capella.yaml"}


def _clone_post(fake, pid):
    posts = [c for c in fake.writes() if c.method == "POST" and c.path == CLUSTERS.format(pid=pid)]
    assert len(posts) == 1, fake.writes()
    return posts[0].body


@pytest.mark.story("CAP-049", "AC1")
def test_cluster_clone_ac1_flags_copies_settings(fake, run, demo):
    r = run("--auto-approve", "cluster", "clone", "nova-demo-01", "nova-demo-weu", "--region", "westeurope")
    assert r.exit_code == 0, r.output
    assert "Cloning nova-demo-01 (nova-demo · azure eastus) → nova-demo-weu (nova-demo · azure westeurope)" in r.output
    assert "+ cluster nova-demo-weu  azure westeurope · multi-AZ · 3 × 8 vCPU/32 GB" in r.output
    for line in ("+ bucket nova-demo-weu/demo", "+ scope nova-demo-weu/demo/inventory",
                 "+ collection nova-demo-weu/demo/inventory/airline", "+ collection nova-demo-weu/demo/inventory/route"):
        assert line in r.output, line
    body = _clone_post(fake, demo["pid"])
    source = fake.clusters[demo["cid"]]["body"]
    assert body["name"] == "nova-demo-weu"
    assert body["cloudProvider"] == {"type": "azure", "region": "westeurope", "cidr": "10.0.1.0/24"}
    assert body["description"] == "Clone of nova-demo-01 (nova-demo, eastus)"
    for key in ("availability", "support"):
        assert body[key] == source[key], key
    # Azure P-type disks: Capella sets storage and IOPS from the type, so only the type is sent (as for create)
    sent = [{**g, "node": {**g["node"], "disk": {"type": g["node"]["disk"]["type"]}}} for g in source["serviceGroups"]]
    assert body["serviceGroups"] == sent
    assert body["couchbaseServer"] == {"version": "7.6.2"}
    clone = next(c for c in file_clusters(demo["file"]) if c["name"] == "nova-demo-weu")
    assert clone["id"] and clone["cloudProvider"]["region"] == "westeurope"
    assert "# cloned from nova-demo-01 (nova-demo, eastus)" in demo["file"].read_text()


@pytest.mark.story("CAP-049", "AC2")
def test_cluster_clone_ac2_interactive_picks_source(fake, run, demo, monkeypatch):
    other = fake.seed_project("nova-other")
    fake.seed_cluster(other, "other-01")
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    # source project 1 (nova-demo), source cluster 1, region, then Enter for name, target project and CIDR; confirm
    r = run("cluster", "clone", input="1\n1\nwesteurope\n\n\n\ny\n")
    assert r.exit_code == 0, r.output
    out = r.output
    asked = ["Source project", "Source cluster", "Region for the clone (azure; nova-demo-01 is in eastus)",
             "Name of the clone [nova-demo-01-westeurope]", "Project of the clone [nova-demo]",
             "Network CIDR (must not overlap other clusters) [10.0.1.0/24]", "Add nova-demo-01-westeurope to capella.yaml"]
    positions = [out.index(q) for q in asked]
    assert positions == sorted(positions), out
    assert "nova-demo-01  azure eastus · multi-AZ · 3 × 8 vCPU/32 GB" in out  # the source list shows size
    assert out.count("[y/N]") == 1
    assert _clone_post(fake, demo["pid"])["name"] == "nova-demo-01-westeurope"


@pytest.mark.story("CAP-049", "AC3")
def test_cluster_clone_ac3_region_bound_values_reset(fake, run, demo):
    fake.schedules[demo["cid"]] = {"activationStatus": "active", "timezone": "US/Eastern", "days": [
        {"day": d, "state": "custom", "from": {"hour": 8}, "to": {"hour": 18}}
        for d in ("monday", "tuesday", "wednesday", "thursday", "friday")] + [
        {"day": d, "state": "off"} for d in ("saturday", "sunday")]}
    assert run("--auto-approve", "sync").exit_code == 0
    assert "hibernation" in demo["file"].read_text()
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "clone", "nova-demo-01", "nova-demo-weu", "--region", "westeurope")
    assert r.exit_code == 0, r.output
    assert "not copied: documents, hibernation schedule" in r.output
    body = _clone_post(fake, demo["pid"])
    assert "zones" not in body and body["cloudProvider"]["cidr"] == "10.0.1.0/24"
    clone = next(c for c in file_clusters(demo["file"]) if c["name"] == "nova-demo-weu")
    assert "hibernation" not in clone and "zones" not in clone
    assert not [c for c in fake.writes() if "onOffSchedule" in c.path]


@pytest.mark.story("CAP-049", "AC4")
def test_cluster_clone_ac4_no_data_model(fake, run, demo):
    r = run("--auto-approve", "cluster", "clone", "nova-demo-01", "nova-demo-weu", "--region", "westeurope",
            "--no-data-model")
    assert r.exit_code == 0, r.output
    assert "+ bucket" not in r.output and "+ scope" not in r.output and "+ collection" not in r.output
    assert "not copied: documents, hibernation schedule, allowed CIDRs, database credentials" in r.output
    assert [c.method for c in fake.writes()] == ["POST"]


@pytest.mark.story("CAP-049", "AC4")
def test_cluster_clone_ac4_with_cidrs(fake, run, demo):
    r = run("--auto-approve", "cluster", "clone", "nova-demo-01", "nova-demo-weu", "--region", "westeurope",
            "--with-cidrs")
    assert r.exit_code == 0, r.output
    assert '+ allowed-cidr nova-demo-weu/203.0.113.10/32' in r.output
    posts = [c.body for c in fake.writes() if c.path.endswith("/allowedcidrs")]
    assert posts and posts[0]["comment"] == "Office (cloned from nova-demo-01)"
    assert "allowed CIDRs" not in r.output.split("not copied:")[1].splitlines()[0]


@pytest.mark.story("CAP-049", "AC4")
def test_cluster_clone_ac4_with_credentials_new_passwords(fake, run, demo, tmp_path):
    r = run("--auto-approve", "cluster", "clone", "nova-demo-01", "nova-demo-weu", "--region", "westeurope",
            "--with-credentials")
    assert r.exit_code == 0, r.output
    assert "+ credential nova-demo-weu/demo_app" in r.output
    created = [u for u in fake.users.values() if u["name"] == "demo_app" and u["_cluster"] != demo["cid"]]
    assert len(created) == 1
    assert created[0]["access"] == fake.users["u-seed-1"]["access"]
    saved = tmp_path / ".capellactl" / "credentials" / "nova-demo-weu.demo_app.json"
    password = json.loads(saved.read_text())["password"]
    assert password and password != fake.users["u-seed-1"]["_password"] and password not in r.output


@pytest.mark.story("CAP-049", "AC5")
def test_cluster_clone_ac5_to_project_with_overrides(fake, run, demo):
    dr = fake.seed_project("nova-dr")
    r = run("--auto-approve", "cluster", "clone", "nova-demo-01", "nova-dr-01", "--region", "westus2",
            "--to-project", "nova-dr", "--support-plan", "developer pro", "--cidr", "10.20.0.0/24")
    assert r.exit_code == 0, r.output
    body = _clone_post(fake, dr)
    assert body["support"]["plan"] == "developer pro" and body["cloudProvider"]["cidr"] == "10.20.0.0/24"
    projects = {p["name"]: p for p in yaml.safe_load(demo["file"].read_text())["projects"]}
    assert [c["name"] for c in projects["nova-dr"]["clusters"]] == ["nova-dr-01"]


@pytest.mark.story("CAP-049", "AC5")
def test_cluster_clone_ac5_missing_target_project(fake, run, demo):
    before = demo["file"].read_text()
    r = run("--auto-approve", "cluster", "clone", "nova-demo-01", "nova-dr-01", "--region", "westus2",
            "--to-project", "nova-dr")
    assert r.exit_code == 3 and "capellactl project create nova-dr" in r.output
    assert fake.writes() == [] and demo["file"].read_text() == before


@pytest.mark.story("CAP-049", "AC6")
@pytest.mark.parametrize("setup,args,code,msg", [
    (None, ["nova-demo-01", "x-01", "--region", "us-east-1"], 3, "us-east-1 is not an azure region name"),
    (None, ["nova-demo-01", "x-01", "--region", "westeurope", "--cidr", "10.0.0.128/25"], 3, "overlaps"),
    (None, ["nova-demo-01", "nova-demo-01", "--region", "westeurope"], 4, "already exists"),
    ("free", ["try-01", "x-01", "--region", "us-east-2"], 4, "free-tier clusters cannot be cloned"),
    ("deploying", ["new-01", "x-01", "--region", "westeurope"], 4, "is deploying; clone it once it is healthy"),
], ids=["region", "cidr", "name", "free", "deploying"])
def test_cluster_clone_ac6_invalid_input_writes_nothing(fake, run, demo, setup, args, code, msg):
    if setup == "free":
        fake.seed_free_cluster(demo["pid"], "try-01")
    elif setup == "deploying":
        fake.seed_cluster(demo["pid"], "new-01", state="deploying")
    before = demo["file"].read_text()
    r = run("--auto-approve", "cluster", "clone", *args)
    assert r.exit_code == code, r.output
    assert msg in r.output
    assert fake.writes() == [] and demo["file"].read_text() == before


@pytest.mark.story("CAP-049", "AC7")
@pytest.mark.parametrize("status", [422, 500])
def test_cluster_clone_ac7_rejected_create_restores_file(fake, run, demo, status):
    before = demo["file"].read_text()
    fake.fail_next("POST", "*/clusters", status)
    r = run("--auto-approve", "cluster", "clone", "nova-demo-01", "nova-demo-weu", "--region", "westeurope")
    assert r.exit_code == 1, r.output
    assert "Failed: cluster nova-demo-weu" in r.output and "was restored" in r.output
    assert "--server-version latest" in r.output
    assert demo["file"].read_text() == before
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "clone", "nova-demo-01", "nova-demo-weu", "--region", "westeurope")
    assert r.exit_code == 0, r.output


@pytest.mark.story("CAP-049", "AC8")
def test_cluster_clone_ac8_idempotent(fake, run, demo):
    args = ("--auto-approve", "cluster", "clone", "nova-demo-01", "nova-demo-weu", "--region", "westeurope")
    assert run(*args).exit_code == 0
    assert run("plan", "--detailed-exitcode").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0 and fake.writes() == []
    r = run("sync", "--dry-run")
    assert r.exit_code == 0, r.output
    r = run(*args)
    assert r.exit_code == 4 and "cluster nova-demo-weu already exists" in r.output
    assert fake.writes() == []


def test_cluster_clone_server_version_latest(fake, run, demo):
    r = run("--auto-approve", "cluster", "clone", "nova-demo-01", "nova-demo-weu", "--region", "westeurope",
            "--server-version", "latest")
    assert r.exit_code == 0, r.output
    assert "couchbaseServer" not in _clone_post(fake, demo["pid"])


def test_cluster_clone_same_region_asks(fake, run, demo):
    r = run("cluster", "clone", "nova-demo-01", "nova-demo-02", "--region", "eastus")
    assert r.exit_code == 1 and "refusing to clone into the same region without approval" in r.output
    assert fake.writes() == []
