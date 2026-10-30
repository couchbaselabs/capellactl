"""CAP-051: create multi-dimensional (MDS) clusters from the CLI."""
from __future__ import annotations

import json

import pytest

from capellactl.cli import console
from tests.conftest import file_clusters, seed_healthy

MDS = ["--group", "data:3x8/32", "--group", "index,query:2x8/32", "--group", "search:2x4/16"]
GP3 = {"type": "gp3", "storage": 50, "iops": 3000}


@pytest.fixture
def imported(fake, run, tmp_path):
    seed_healthy(fake)
    assert run("import").exit_code == 0
    fake.reset_calls()
    return tmp_path / "capella.yaml"


def _cluster(path, name):
    return next(c for c in file_clusters(path) if c["name"] == name)


@pytest.mark.story("CAP-051", "AC1")
def test_cluster_mds_ac1_create_body_matches_fixture(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "nova-prod-01", "--provider", "aws", *MDS)
    assert r.exit_code == 0, r.output
    posts = fake.calls("POST", "*/clusters")
    assert len(posts) == 1
    assert posts[0].body["serviceGroups"] == [
        {"node": {"compute": {"cpu": 8, "ram": 32}, "disk": GP3}, "numOfNodes": 3, "services": ["data"]},
        {"node": {"compute": {"cpu": 8, "ram": 32}, "disk": GP3}, "numOfNodes": 2, "services": ["index", "query"]},
        {"node": {"compute": {"cpu": 4, "ram": 16}, "disk": GP3}, "numOfNodes": 2, "services": ["search"]},
    ]
    assert "cluster nova-prod-01: healthy" in r.output
    assert [g["services"] for g in _cluster(imported, "nova-prod-01")["serviceGroups"]] == \
        [["data"], ["index", "query"], ["search"]]


@pytest.mark.story("CAP-051", "AC1")
def test_cluster_mds_ac1_plan_lines_per_group(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "nova-prod-01", *MDS, "--no-apply")
    assert r.exit_code == 0, r.output
    assert "+ cluster nova-prod-01  aws us-east-1 · multi-AZ · 3 service groups · 7 nodes · developer pro" in r.output
    assert "+ serviceGroups[data]         3 × 8 vCPU/32 GB gp3 50 GB" in r.output
    assert "+ serviceGroups[index,query]  2 × 8 vCPU/32 GB gp3 50 GB" in r.output
    assert "+ serviceGroups[search]       2 × 4 vCPU/16 GB gp3 50 GB" in r.output
    assert "3 groups · 7 nodes (data 3 × 8/32 · index,query 2 × 8/32 · search 2 × 4/16)" in r.output


@pytest.mark.story("CAP-051", "AC3")
@pytest.mark.parametrize("extra,flags", [
    (["--nodes", "3"], "--nodes"), (["--cpu", "8", "--ram", "32"], "--cpu, --ram"),
    (["--services", "data"], "--services"), (["--size", "small"], "--size"),
])
def test_cluster_mds_ac3_conflicting_flags(fake, run, imported, extra, flags):
    before = imported.read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "create", "bad-01", *MDS, *extra)
    assert r.exit_code == 3 and f"--group sets nodes, size and services per group; remove {flags}" in r.output
    assert imported.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-051", "AC3")
def test_cluster_mds_ac3_duplicate_group_key(fake, run, imported):
    before = imported.read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "create", "bad-01", "--group", "data:3x8/32", "--group", "index,query:2x8/32",
            "--group", "query,index:2x4/16")
    assert r.exit_code == 3 and "two groups run index,query; each group needs a different set of services" in r.output
    assert imported.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-051", "AC4")
@pytest.mark.parametrize("groups,msg", [
    (["index,query:3x8/32", "search:2x4/16"], "at least one service group must run the data service"),
    (["data:2x8/32"], "must be between 3 and 27"),
    (["data:3x8/32", "search:25x4/16"], "additional service groups allow 2–24 nodes"),
    (["data:20x8/32", "search:8x4/16"], "a cluster can have at most 27 nodes (declared 28)"),
])
def test_cluster_mds_ac4_limits(fake, run, imported, groups, msg):
    args = [a for g in groups for a in ("--group", g)]
    r = run("--auto-approve", "cluster", "create", "bad-01", *args)
    assert r.exit_code == 3 and msg in r.output, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-051", "AC4")
def test_cluster_mds_ac4_single_node_one_group(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "bad-01", "--single-node", "--group", "data:1x4/16",
            "--group", "search:2x4/16")
    assert r.exit_code == 3 and "singleNode clusters have exactly one service group" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-051", "AC4")
def test_cluster_mds_ac4_data_group_first(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "nova-prod-01", "--group", "search:2x4/16", "--group", "data:3x8/32")
    assert r.exit_code == 0, r.output
    assert [g["services"] for g in fake.calls("POST", "*/clusters")[0].body["serviceGroups"]] == [["data"], ["search"]]


@pytest.mark.story("CAP-051", "AC5")
@pytest.mark.parametrize("provider,region,extra,disks", [
    ("aws", "us-east-1", ["--disk-size", "100"],
     [{"type": "gp3", "storage": 100, "iops": 4370}, {"type": "gp3", "storage": 200, "iops": 5740}]),  # CAP-060 AC3
    ("gcp", "us-east1", ["--disk-size", "100"], [{"type": "pd-ssd", "storage": 100}, {"type": "pd-ssd", "storage": 200}]),
    ("azure", "eastus", [], [{"type": "P6", "autoExpansion": True}, {"type": "P6"}]),
])
def test_cluster_mds_ac5_disk_per_group(fake, run, imported, provider, region, extra, disks):
    second = "index,query:2x8/32" + ("" if provider == "azure" else ":size=200")
    first = "data:3x8/32" + (":auto-expansion=true" if provider == "azure" else "")
    r = run("--auto-approve", "cluster", "create", "nova-prod-01", "--provider", provider, "--region", region,
            *extra, "--group", first, "--group", second)
    assert r.exit_code == 0, r.output
    body = fake.calls("POST", "*/clusters")[0].body
    assert [g["node"]["disk"] for g in body["serviceGroups"]] == disks


@pytest.mark.story("CAP-051", "AC5")
def test_cluster_mds_ac5_auto_expansion_azure_only(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "bad-01", "--group", "data:3x8/32:auto-expansion=true")
    assert r.exit_code == 3 and "autoExpansion is for azure disks only" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-051", "AC6")
def test_cluster_mds_ac6_interactive_two_groups(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    answers = ["provisioned", "aws", "custom", "multiple",  # a single word is enough
               "data", "3", "4", "", "", "",  # group 1: data, 3 nodes, size 4 (8/32), disk type, size, IOPS default
               "y",
               "index,query", "2", "2", "", "100", "",  # group 2: 4/32 with gp3 100 GB (CAP-060 picker)
               "n", "", "", "", "y"]
    r = run("cluster", "create", "nova-prod-01", input="\n".join(answers) + "\n")
    assert r.exit_code == 0, r.output
    assert "Service group 2  (nodes so far: 3 of 27)" in r.output and "Node size (vCPU / RAM GB)" in r.output
    groups = _cluster(imported, "nova-prod-01")["serviceGroups"]
    assert [(g["services"], g["numOfNodes"], g["node"]["compute"]) for g in groups] == [
        (["data"], 3, {"cpu": 8, "ram": 32}), (["index", "query"], 2, {"cpu": 4, "ram": 32})]
    assert groups[1]["node"]["disk"]["storage"] == 100
    assert "2 groups · 5 nodes (data 3 × 8/32 · index,query 2 × 4/32)" in r.output


@pytest.mark.story("CAP-051", "AC6")
def test_cluster_mds_ac6_interactive_reasks_bad_answer(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    answers = ["provisioned", "aws", "custom", "multiple groups",
               "dat", "data", "2", "3", "4", "", "", "", "y",
               "data", "cache", "search", "25", "2", "1", "", "", "",
               "n", "", "", "", "y"]
    r = run("cluster", "create", "nova-prod-01", input="\n".join(answers) + "\n")
    assert r.exit_code == 0, r.output
    for msg in ("unknown service 'dat'; did you mean data?", "this group needs 3–27 nodes",
                "a group already runs data", "unknown service 'cache'", "this group needs 2–24 nodes"):
        assert msg in r.output, msg
    assert [g["services"] for g in _cluster(imported, "nova-prod-01")["serviceGroups"]] == [["data"], ["search"]]


@pytest.mark.story("CAP-051", "AC6")
def test_cluster_mds_ac6_one_group_keeps_questions(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    answers = ["provisioned", "aws", "custom", "one group", "3", "8", "32", "", "", "", "", "", "", "y"]
    r = run("cluster", "create", "nova-qa-01", input="\n".join(answers) + "\n")
    assert r.exit_code == 0, r.output
    assert "vCPUs per node" in r.output and "Node size" not in r.output
    assert _cluster(imported, "nova-qa-01")["serviceGroups"][0]["node"]["compute"] == {"cpu": 8, "ram": 32}


@pytest.mark.story("CAP-051", "AC7")
def test_cluster_mds_ac7_rerun_zero_writes(fake, run, imported):
    r = run("--auto-approve", "-o", "json", "cluster", "create", "nova-prod-01", *MDS)
    assert r.exit_code == 0, r.output
    notes = [n for a in json.loads(r.output[r.output.index("{"):])["plan"]["actions"] for n in a.get("notes", [])]
    assert [n.split("]")[0] for n in notes if n.startswith("+ serviceGroups[")] == \
        ["+ serviceGroups[data", "+ serviceGroups[index,query", "+ serviceGroups[search"]
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output
    r = run("--auto-approve", "cluster", "create", "nova-prod-01", *MDS)
    assert r.exit_code == 4 and "already exists" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-051", "AC7")
def test_cluster_mds_ac7_no_apply_then_apply(fake, run, imported):
    assert run("--auto-approve", "cluster", "create", "nova-prod-01", *MDS, "--no-apply").exit_code == 0
    assert fake.writes() == []
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert len(fake.calls("POST", "*/clusters")[0].body["serviceGroups"]) == 3


@pytest.mark.story("CAP-051", "AC8")
def test_cluster_mds_ac8_help_and_options(fake, run, imported):
    r = run("cluster", "create", "--help")
    assert "SERVICES:NODESxCPU/RAM[:DISK]" in r.output and "--group data:3x8/32 --group index,query:2x8/32" in r.output
    assert "cluster clone SOURCE NEW_NAME --region REGION --no-data-model" in r.output
    r = run("cluster", "options")
    assert r.exit_code == 0, r.output
    assert "services         data, index, query, search, analytics, eventing" in r.output
    assert "first group 3–27 nodes, other groups 2–24, at most 27 per cluster, one group runs data" in r.output
    assert "aws    4/16, 4/32, 8/16, 8/32" in r.output
    r = run("help", "scaling")
    assert "--group data:3x8/32" in r.output


@pytest.mark.story("CAP-051", "AC9")
def test_cluster_mds_ac9_interactive_offers_known_sizes(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    answers = ["provisioned", "aws", "custom", "multiple groups", "data", "3", "18", "6", "30", "", "", "", "n",
               "", "", "", "y"]
    r = run("cluster", "create", "nova-prod-01", input="\n".join(answers) + "\n")
    assert r.exit_code == 0, r.output
    assert " 1) 4/16" in r.output and "17) 64/512" in r.output and "18) other" in r.output
    assert "2/8" not in r.output.split("Node size")[1].split("Choose")[0]  # single-node only
    assert _cluster(imported, "nova-prod-01")["serviceGroups"][0]["node"]["compute"] == {"cpu": 6, "ram": 30}


@pytest.mark.story("CAP-051", "AC9")
def test_cluster_mds_ac9_unknown_size_warns(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "nova-prod-01", "--group", "data:3x8/30", "--group",
            "search:2x4/16", "--no-apply")
    assert r.exit_code == 0, r.output
    warning = ("! serviceGroups[data]: 8 vCPU/30 GB is not a known aws size; Capella may reject it "
               "(see 'capellactl cluster options')")
    assert warning in r.output
    assert r.output.index(warning) < r.output.index("updated (previous version kept")
    assert "serviceGroups[search]: 4 vCPU" not in r.output


@pytest.mark.story("CAP-051", "AC10")
def test_cluster_mds_ac10_422_restores_file(fake, run, imported):
    before = imported.read_text(encoding="utf-8")
    fake.fail_next("POST", "*/clusters", 422, code=422)
    r = run("--auto-approve", "cluster", "create", "nova-prod-01", "--group", "data:3x8/30", "--group", "search:2x4/16")
    assert r.exit_code == 1, r.output
    assert "was restored" in r.output
    assert imported.read_text(encoding="utf-8") == before
    assert not any(c["body"]["name"] == "nova-prod-01" for c in fake.clusters.values())
    r = run("--auto-approve", "cluster", "create", "nova-prod-01", "--group", "data:3x8/32", "--group", "search:2x4/16")
    assert r.exit_code == 0, r.output


@pytest.mark.story("CAP-051", "AC10")
def test_cluster_mds_ac10_deployment_failed_not_deleted(fake, run, imported):
    fake.fail_deploy_next = True
    r = run("--auto-approve", "cluster", "create", "nova-prod-01", *MDS)
    assert r.exit_code == 1, r.output
    assert "deploymentFailed" in r.output
    assert fake.calls("DELETE", "*/clusters/*") == []


@pytest.mark.story("CAP-051", "AC6")
def test_cluster_mds_ac6_default_is_unused_services(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    answers = ["provisioned", "aws", "custom", "multiple",
               "data", "3", "4", "", "", "", "y",
               "index,query", "2", "1", "", "", "", "y",
               "", "2", "1", "", "", "",  # Enter: one group with every service not used yet
               "n", "", "", "", "y"]
    r = run("cluster", "create", "nova-prod-01", input="\n".join(answers) + "\n")
    assert r.exit_code == 0, r.output
    assert "Services [data,index,query,search,analytics,eventing]:" in r.output
    assert "Services [index,query,search,analytics,eventing]:" in r.output
    assert "Services [search,analytics,eventing]:" in r.output
    groups = _cluster(imported, "nova-prod-01")["serviceGroups"]
    assert groups[2]["services"] == ["analytics", "eventing", "search"]
