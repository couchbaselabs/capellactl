"""CAP-053: advanced cluster create options (server version, single node, zone, CMEK, private DNS, auto-expansion)."""
from __future__ import annotations

import pytest
import yaml

from tests.conftest import file_clusters, seed_healthy


@pytest.fixture
def imported(fake, run, tmp_path):
    seed_healthy(fake)
    assert run("import").exit_code == 0
    fake.reset_calls()
    return tmp_path / "capella.yaml"


def _cluster(path, name):
    return next(c for c in file_clusters(path) if c["name"] == name)


@pytest.mark.story("CAP-053", "AC1")
@pytest.mark.parametrize("args,field,value", [
    (["--server-version", "8.0"], "couchbaseServer", {"version": "8.0"}),
    (["--availability", "single", "--zone", "use1-az1"], "zones", ["use1-az1"]),
    (["--cmek-id", "key-1"], "cmekId", "key-1"),
    (["--private-dns"], "enablePrivateDNSResolution", True),
])
def test_cluster_adv_ac1_option_in_body(fake, run, imported, args, field, value):
    r = run("--auto-approve", "cluster", "create", "nova-adv-01", *args)
    assert r.exit_code == 0, r.output
    body = fake.calls("POST", "*/clusters")[0].body
    assert body[field] == value
    others = {"couchbaseServer", "zones", "cmekId", "enablePrivateDNSResolution"} - {field}
    assert not others & set(body)
    assert _cluster(imported, "nova-adv-01")[field] == value
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output


@pytest.mark.story("CAP-053", "AC1")
def test_cluster_adv_ac1_auto_expansion_in_body(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "nova-az-01", "--provider", "azure", "--disk-auto-expansion")
    assert r.exit_code == 0, r.output
    assert fake.calls("POST", "*/clusters")[0].body["serviceGroups"][0]["node"]["disk"] == \
        {"type": "P6", "autoExpansion": True}


@pytest.mark.story("CAP-053", "AC2")
def test_cluster_adv_ac2_single_node_custom(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "nova-dev-03", "--single-node", "--cpu", "8", "--ram", "32")
    assert r.exit_code == 0, r.output
    body = fake.calls("POST", "*/clusters")[0].body
    assert body["configurationType"] == "singleNode" and body["availability"] == {"type": "single"}
    assert body["serviceGroups"] == [{"node": {"compute": {"cpu": 8, "ram": 32},
                                               "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
                                      "numOfNodes": 1, "services": ["data", "index", "query"]}]


@pytest.mark.story("CAP-053", "AC2")
@pytest.mark.parametrize("args,msg", [
    (["--nodes", "3"], "singleNode clusters have exactly 1 node; remove --nodes"),
    (["--availability", "multi"], "singleNode clusters must use availability: single"),
    (["--group", "data:1x4/16", "--group", "search:2x4/16"], "singleNode clusters have exactly one service group"),
    (["--services", "data,analytics"], "singleNode clusters run only data, index, query and search"),
    (["--size", "dev"], "--single-node sets the size; remove --size"),
])
def test_cluster_adv_ac2_single_node_refused(fake, run, imported, args, msg):
    before = imported.read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "create", "bad-01", "--single-node", *args)
    assert r.exit_code == 3 and msg in r.output, r.output
    assert imported.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-053", "AC3")
@pytest.mark.parametrize("args,msg", [
    (["--zone", "use1-az1"], "zones can only be set for availability: single"),
    (["--disk-auto-expansion"], "autoExpansion is for azure disks only"),
    (["--provider", "gcp", "--disk-auto-expansion"], "autoExpansion is for azure disks only"),
    (["--server-version", "latest"], "--server-version takes a version like 8.0 or 7.6.4 (got 'latest')"),
    (["--cmek-id", " "], "--cmek-id needs the ID of an existing encryption key"),
])
def test_cluster_adv_ac3_rules(fake, run, imported, args, msg):
    r = run("--auto-approve", "cluster", "create", "bad-01", *args)
    assert r.exit_code == 3 and msg in r.output, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-053", "AC4")
def test_cluster_adv_ac4_422_restores_file(fake, run, imported):
    before = imported.read_text(encoding="utf-8")
    fake.fail_next("POST", "*/clusters", 422, code=422)
    r = run("--auto-approve", "cluster", "create", "nova-adv-01", "--server-version", "6.0")
    assert r.exit_code == 1 and "was restored" in r.output, r.output
    assert imported.read_text(encoding="utf-8") == before


@pytest.mark.story("CAP-053", "AC5")
def test_cluster_adv_ac5_version_immutable(fake, run, imported):
    assert run("--auto-approve", "cluster", "create", "nova-adv-01", "--server-version", "7.6").exit_code == 0
    data = yaml.safe_load(imported.read_text(encoding="utf-8"))
    cl = next(c for c in data["projects"][0]["clusters"] if c["name"] == "nova-adv-01")
    cl["couchbaseServer"]["version"] = "8.0"
    imported.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4 and "couchbaseServer.version" in r.output, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-053", "AC5")
def test_cluster_adv_ac5_update_auto_expansion(fake, run, imported):
    assert run("--auto-approve", "cluster", "create", "nova-az-01", "--provider", "azure").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "update", "nova-az-01", "--disk-auto-expansion")
    assert r.exit_code == 0, r.output
    puts = fake.calls("PUT", "*/clusters/*")
    assert len(puts) == 1 and puts[0].body["serviceGroups"][0]["node"]["disk"]["autoExpansion"] is True
    assert _cluster(imported, "nova-az-01")["serviceGroups"][0]["node"]["disk"]["autoExpansion"] is True
    r = run("--auto-approve", "cluster", "update", "nova-dev-01", "--disk-auto-expansion")
    assert r.exit_code == 3 and "auto-expansion is for azure disks only" in r.output


@pytest.mark.story("CAP-053", "AC6")
def test_cluster_adv_ac6_help_and_options(fake, run, imported):
    r = run("cluster", "create", "--help")
    advanced = r.output.split("Advanced options (not asked; set only on the command line):")[1]
    for opt in ("--single-node", "--server-version", "--zone", "--cmek-id", "--private-dns", "--disk-auto-expansion"):
        assert opt in advanced and opt not in r.output.split("Advanced options")[0], opt
    assert "--single-node --cpu 8 --ram 32" in r.output
    r = run("cluster", "options")
    assert "server versions  in use by your clusters:" in r.output
    for field, opt in (("clusters.zones", "--zone"), ("clusters.cmekId", "--cmek-id"),
                       ("clusters.enablePrivateDNSResolution", "--private-dns"),
                       ("clusters.couchbaseServer.version", "--server-version"),
                       ("clusters.configurationType", "--single-node")):
        assert f"capellactl cluster create NAME {opt}" in run("help", "config", field).output, field


@pytest.mark.story("CAP-053", "AC7")
def test_cluster_adv_ac7_rerun_zero_writes(fake, run, imported):
    args = ["--server-version", "8.0", "--cmek-id", "key-1", "--private-dns"]
    assert run("--auto-approve", "cluster", "create", "nova-adv-01", *args).exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert "No changes" in r.output and fake.writes() == []


@pytest.mark.story("CAP-053", "AC7")
def test_cluster_adv_ac7_import_round_trip(fake, run, tmp_path):
    pid = fake.seed_project("nova-adv")
    fake.seed_cluster(pid, "made-in-ui", couchbaseServer={"version": "7.6.4"}, cmekId="key-1",
                      enablePrivateDNSResolution=True, cloudProvider={"type": "azure", "region": "eastus",
                                                                      "cidr": "10.20.0.0/24"},
                      serviceGroups=[{"node": {"compute": {"cpu": 4, "ram": 16},
                                               "disk": {"type": "P6", "storage": 64, "iops": 240,
                                                        "autoExpansion": True}},
                                      "numOfNodes": 3, "services": ["data", "index", "query"]}])
    assert run("import").exit_code == 0
    cl = file_clusters(tmp_path / "capella.yaml")[0]
    assert cl["cmekId"] == "key-1" and cl["enablePrivateDNSResolution"] is True
    assert cl["couchbaseServer"] == {"version": "7.6.4"}
    assert cl["serviceGroups"][0]["node"]["disk"]["autoExpansion"] is True
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert "No changes" in r.output, r.output
