"""CAP-036: import an existing project and clusters into capella.yaml."""
from __future__ import annotations

import pytest
import yaml

from capellactl.cli import console
from tests.conftest import assert_no_secret, file_clusters, file_projects, seed_healthy

PASS = "Existing!Secret-77"


def _rich(fake, *, turned_off: bool = False):
    """Project + cluster with schedule, CIDRs (one expired), buckets/scopes/collections, credentials."""
    pid, cid = seed_healthy(fake, deletionProtection=True)
    if turned_off:
        fake.clusters[cid]["seq"] = [("turnedOff", -1.0)]
    fake.schedules[cid] = {"activationStatus": "active", "timezone": "US/Pacific", "days": [
        *({"day": d, "state": "custom", "from": {"hour": 8, "minute": 0}, "to": {"hour": 18, "minute": 0}}
          for d in ("monday", "tuesday", "wednesday", "thursday", "friday")),
        {"day": "saturday", "state": "off"}, {"day": "sunday", "state": "off"}]}
    fake.cidrs["cidr-a"] = {"id": "cidr-a", "_cluster": cid, "cidr": "203.0.113.10/32", "comment": "Office VPN",
                            "status": "active"}
    fake.cidrs["cidr-b"] = {"id": "cidr-b", "_cluster": cid, "cidr": "198.51.100.0/24", "status": "expired"}
    orders = fake.seed_bucket(cid, "orders", memoryAllocationInMb=1024, storageBackend="magma",
                              durabilityLevel="majority")
    fake.scopes[(cid, orders)]["inventory"] = {"items": {"name": "items", "maxTTL": 0},
                                               "suppliers": {"name": "suppliers", "maxTTL": -1}}
    fake.scopes[(cid, orders)]["billing"] = {"invoices": {"name": "invoices", "maxTTL": 0}}
    fake.seed_bucket(cid, "sessions", type="ephemeral", evictionPolicy="nruEviction", memoryAllocationInMb=256,
                     storageBackend=None)
    fake.users["u-1"] = {"id": "u-1", "_cluster": cid, "name": "orders_app", "_password": PASS, "access": [
        {"privileges": ["data_writer", "data_reader"], "resources": {"buckets": [
            {"name": "orders", "scopes": [{"name": "inventory", "collections": ["items", "suppliers"]}]}]}}]}
    fake.users["u-2"] = {"id": "u-2", "_cluster": cid, "name": "reporting_ro", "_password": PASS,
                         "access": [{"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders"}]}}]}
    fake.users["u-3"] = {"id": "u-3", "_cluster": cid, "name": "dba", "access": [], "userRoles": ["admin_role"]}
    return pid, cid


@pytest.mark.story("CAP-036", "AC1")
def test_import_ac1_all_kinds_exported(fake, run, tmp_path):
    _rich(fake)
    r = run("import")
    assert r.exit_code == 0, r.output
    assert ("Imported 1 project, 1 cluster, 2 buckets, 2 scopes, 3 collections, 2 credentials, 1 allowed CIDR, "
            "1 hibernation schedule into capella.yaml") in r.output
    data = yaml.safe_load((tmp_path / "capella.yaml").read_text(encoding="utf-8"))
    cl = data["projects"][0]["clusters"][0]
    assert data["projects"][0]["name"] == "nova-dev" and cl["name"] == "nova-dev-01" and cl["deletionProtection"] is True
    assert cl["hibernation"] == {"timezone": "US/Pacific", "weekdays": "08:00-18:00", "weekend": "off"}
    assert [b["name"] for b in cl["buckets"]] == ["orders", "sessions"]
    assert [s["name"] for s in cl["buckets"][0]["scopes"]] == ["inventory", "billing"]
    assert [u["name"] for u in cl["databaseCredentials"]] == ["orders_app", "reporting_ro"]


@pytest.mark.story("CAP-036", "AC1")
def test_import_ac1_expired_cidr_skipped(fake, run, tmp_path):
    _rich(fake)
    run("import")
    cl = file_clusters(tmp_path / "capella.yaml")[0]
    assert cl["allowedCidrs"] == [{"cidr": "203.0.113.10/32", "comment": "Office VPN"}]


@pytest.mark.story("CAP-036", "AC1")
def test_import_ac1_any_ip_cidr_records_allow_any_ip(fake, run, tmp_path):
    _rich(fake)
    cid = fake.cidrs["cidr-a"]["_cluster"]
    fake.cidrs["cidr-c"] = {"id": "cidr-c", "_cluster": cid, "cidr": "0.0.0.0/0", "status": "active"}
    assert run("import").exit_code == 0
    cl = file_clusters(tmp_path / "capella.yaml")[0]
    assert cl["allowAnyIp"] is True and list(cl).index("allowAnyIp") < list(cl).index("hibernation")
    assert run("validate").exit_code == 0


@pytest.mark.story("CAP-036", "AC1")
def test_import_ac1_advanced_credential_commented(fake, run, tmp_path):
    _rich(fake)
    run("import")
    text = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert "# dba is an advanced credential (userRoles)" in text
    assert "      # - name: dba" in text and "admin_role" in text
    assert "dba" not in [u["name"] for u in yaml.safe_load(text)["projects"][0]["clusters"][0]["databaseCredentials"]]


SEEDS = {
    "minimal": lambda f: seed_healthy(f),
    "rich": _rich,
    "single-node": lambda f: seed_healthy(f, configurationType="singleNode", availability={"type": "single"},
                                         serviceGroups=[{"node": {"compute": {"cpu": 4, "ram": 16},
                                                                  "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
                                                         "numOfNodes": 1, "services": ["data", "index", "query"]}]),
    "two-groups": lambda f: seed_healthy(f, serviceGroups=[
        {"node": {"compute": {"cpu": 8, "ram": 32}, "disk": {"type": "io2", "storage": 100, "iops": 5000}},
         "numOfNodes": 3, "services": ["query", "data", "index"]},
        {"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
         "numOfNodes": 2, "services": ["search"]}]),
    "azure": lambda f: seed_healthy(f, cloudProvider={"type": "azure", "region": "eastus", "cidr": "10.1.0.0/23"},
                                    serviceGroups=[{"node": {"compute": {"cpu": 4, "ram": 16},
                                                             "disk": {"type": "P10", "autoExpansion": False}},
                                                    "numOfNodes": 3, "services": ["data", "index", "query"]}]),
    "gcp-enterprise": lambda f: seed_healthy(f, cloudProvider={"type": "gcp", "region": "us-east1",
                                                               "cidr": "10.2.0.0/23"},
                                             support={"plan": "enterprise", "timezone": "ET"},
                                             serviceGroups=[{"node": {"compute": {"cpu": 4, "ram": 16},
                                                                      "disk": {"type": "pd-ssd", "storage": 100}},
                                                             "numOfNodes": 3, "services": ["data", "index", "query"]}]),
}


@pytest.mark.story("CAP-036", "AC2")
@pytest.mark.parametrize("full", [False, True], ids=["minimal", "full"])
@pytest.mark.parametrize("seed", list(SEEDS))
def test_import_ac2_round_trip_no_changes(fake, run, seed, full):
    SEEDS[seed](fake)
    r = run("import", *(["--full"] if full else []))
    assert r.exit_code == 0, r.output
    assert run("validate").exit_code == 0
    fake.reset_calls()
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0, r.output
    r = run("--auto-approve", "apply")
    assert "No changes. Capella matches capella.yaml." in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-036", "AC2")
def test_import_ac2_round_trip_children_with_reconcilers(fake, run, stub_tree):
    """Buckets, scopes, collections, CIDRs and credentials also round-trip once their reconcilers exist."""
    _rich(fake)
    assert run("import").exit_code == 0
    fake.reset_calls()
    assert run("plan", "--detailed-exitcode").exit_code == 0
    assert fake.writes() == []


@pytest.mark.story("CAP-036", "AC3")
def test_import_ac3_only_gets(fake, run):
    _rich(fake)
    assert run("import").exit_code == 0
    assert fake.calls() and fake.writes() == []


@pytest.mark.story("CAP-036", "AC4")
def test_import_ac4_no_secrets(fake, run, tmp_path):
    _rich(fake)
    r = run("import")
    text = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert "password:" not in text
    assert text.count("# password not exported (Capella never returns it)") == 2
    assert_no_secret(text + r.output, PASS, "test-api-key-0123456789")


@pytest.mark.story("CAP-036", "AC5")
def test_import_ac5_cluster_filter(fake, run, tmp_path):
    pid, _ = seed_healthy(fake)
    fake.seed_cluster(pid, "nova-dev-02")
    assert run("import", "--cluster", "nova-dev-02").exit_code == 0
    assert [c["name"] for c in file_clusters(tmp_path / "capella.yaml")] == ["nova-dev-02"]
    r = run("import", "--cluster", "nope", "--force")
    assert r.exit_code == 1 and "not found in project nova-dev: nope" in r.output


@pytest.mark.story("CAP-036", "AC5")
def test_import_ac5_ambiguous_names_pinned(fake, run, tmp_path):
    pid, a = seed_healthy(fake)
    b = fake.seed_cluster(pid, "nova-dev-01")
    r = run("import")
    assert r.exit_code == 0 and "[WARNING]: 2 clusters are named nova-dev-01; capella.yaml tells them apart by id" in r.output
    clusters = file_clusters(tmp_path / "capella.yaml")
    assert [c["id"] for c in clusters] == [a, b]
    assert run("plan", "--detailed-exitcode").exit_code == 0
    run("import", "--cluster-id", b, "--force")
    assert [c["id"] for c in file_clusters(tmp_path / "capella.yaml")] == [b]


@pytest.mark.story("CAP-036", "AC6")
def test_import_ac6_minimal_omits_defaults(fake, run, tmp_path):
    _, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "plain", memoryAllocationInMb=512)
    run("import")
    b = file_clusters(tmp_path / "capella.yaml")[0]["buckets"][0]
    assert b == {"name": "plain", "storageBackend": "couchstore", "memoryAllocationInMb": 512,
                 "evictionPolicy": "fullEviction"}


@pytest.mark.story("CAP-036", "AC6")
def test_import_ac6_full_has_all_fields(fake, run, tmp_path):
    _, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "plain", memoryAllocationInMb=512)
    run("import", "--full")
    data = yaml.safe_load((tmp_path / "capella.yaml").read_text(encoding="utf-8"))
    cl0 = data["projects"][0]["clusters"][0]
    b = cl0["buckets"][0]
    for f in ("type", "replicas", "durabilityLevel", "timeToLiveInSeconds", "flushEnabled", "priority",
              "bucketConflictResolution"):
        assert f in b, f
    assert cl0["deletionProtection"] is False and "configurationType" in cl0


@pytest.mark.story("CAP-036", "AC7")
def test_import_ac7_schedule_compacted(fake, run, tmp_path):
    _rich(fake)
    run("import")
    text = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert "weekdays: 08:00-18:00" in text and "weekend: 'off'" in text


@pytest.mark.story("CAP-036", "AC7")
def test_import_ac7_schedule_irregular_per_day(fake, run, tmp_path):
    _, cid = seed_healthy(fake)
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    fake.schedules[cid] = {"activationStatus": "paused", "timezone": "Europe/London", "days": [
        {"day": "monday", "state": "on"}, {"day": "tuesday", "state": "custom", "from": {"hour": 9, "minute": 30},
                                           "to": {"hour": 0, "minute": 0}},
        *({"day": d, "state": "off"} for d in days[2:])]}
    run("import")
    h = file_clusters(tmp_path / "capella.yaml")[0]["hibernation"]
    # the most common weekday value becomes weekdays; the other days are overrides (as `schedule set` writes it)
    assert h["weekdays"] == "off" and h["monday"] == "on" and h["tuesday"] == "09:30-24:00" and "friday" not in h
    assert h["weekend"] == "off" and h["paused"] is True


@pytest.mark.story("CAP-036", "AC8")
def test_import_ac8_existing_file_and_stdout(fake, run, tmp_path, monkeypatch):
    seed_healthy(fake)
    (tmp_path / "capella.yaml").write_text("old content\n", encoding="utf-8")
    r = run("import")
    assert r.exit_code == 1 and "already exists and is not a capellactl file\n[ACTION]: Pass --force" in r.output
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("import", input="n\n")
    assert "Import cancelled; nothing was written." in r.output
    assert (tmp_path / "capella.yaml").read_text(encoding="utf-8") == "old content\n"
    r = run("import", input="y\n")
    assert r.exit_code == 0 and (tmp_path / "capella.yaml.bak").read_text(encoding="utf-8") == "old content\n"
    r = run("import", "--stdout")
    assert r.exit_code == 0 and r.stdout.startswith("# Imported by capellactl")
    assert yaml.safe_load(r.stdout)["projects"][0]["name"] == "nova-dev"


@pytest.mark.story("CAP-036", "AC9")
def test_import_ac9_turned_off_cluster(fake, run, tmp_path):
    _rich(fake, turned_off=True)
    fake.fail_next("GET", "*/buckets", 500, times=6)  # what Capella answers while the cluster is off
    r = run("import")
    assert r.exit_code == 0, r.output
    assert "[WARNING]: cluster nova-dev-01: buckets and database credentials not imported (turnedOff)\n[ACTION]: Turn it on" in r.output
    assert "retrying" not in r.output  # not even asked
    text = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert "# not imported: buckets and database credentials (the cluster is turnedOff;" in text
    cl = yaml.safe_load(text)["projects"][0]["clusters"][0]
    assert "hibernation" in cl and "allowedCidrs" in cl
    assert "buckets" not in cl and "databaseCredentials" not in cl


def test_import_empty_project_points_to_cluster_create(fake, run, tmp_path):
    fake.seed_project("alpha")
    r = run("import")
    assert r.exit_code == 0, r.output
    assert file_projects(tmp_path / "capella.yaml")[0]["clusters"] == []
    assert "Next: capellactl cluster create NAME" in r.output
    assert "To create one, run: capellactl cluster create NAME" in (tmp_path / "capella.yaml").read_text(encoding="utf-8")
