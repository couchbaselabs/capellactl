"""CAP-052: cluster group list, add and remove."""
from __future__ import annotations

import json

import pytest

from tests.conftest import file_clusters, seed_healthy

GP3 = {"type": "gp3", "storage": 50, "iops": 3000}


def _group(services, nodes=2, cpu=4, ram=16):
    return {"node": {"compute": {"cpu": cpu, "ram": ram}, "disk": dict(GP3)}, "numOfNodes": nodes, "services": services}


@pytest.fixture
def three_groups(fake, run, tmp_path):
    pid, cid = seed_healthy(fake)
    fake.clusters[cid]["body"]["serviceGroups"] = [_group(["data", "index", "query"], 3, 8, 32), _group(["search"]),
                                                   _group(["index", "search"])]
    assert run("import").exit_code == 0
    fake.reset_calls()
    return tmp_path / "capella.yaml", cid


@pytest.fixture
def imported(fake, run, tmp_path):
    _, cid = seed_healthy(fake)
    assert run("import").exit_code == 0
    fake.reset_calls()
    return tmp_path / "capella.yaml", cid


def _keys(path):
    return [",".join(g["services"]) for g in file_clusters(path)[0]["serviceGroups"]]


@pytest.mark.story("CAP-052", "AC1")
def test_group_cmd_ac1_list(fake, run, three_groups):
    r = run("cluster", "group", "list", "nova-dev-01")
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0].split() == ["S.NO", "SERVICES", "NODES", "vCPU", "RAM", "GB", "DISK"]
    assert lines[1].split()[:5] == ["1", "data,index,query", "3", "8", "32"] and "gp3 50 GB 3000 IOPS" in lines[1]
    assert lines[3].split()[:2] == ["3", "index,search"]
    assert "total nodes: 7 of 27" in r.output
    r = run("-o", "json", "cluster", "group", "list", "nova-dev-01")
    assert [g["services"] for g in json.loads(r.output)] == [["data", "index", "query"], ["search"], ["index", "search"]]
    r = run("cluster", "group", "list", "nope-01")
    assert r.exit_code != 0 and "nope-01" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-052", "AC2")
def test_group_cmd_ac2_add_body(fake, run, imported):
    path, _ = imported
    r = run("--auto-approve", "cluster", "group", "add", "nova-dev-01", "--services", "search", "--nodes", "2")
    assert r.exit_code == 0, r.output
    assert "+ serviceGroups[search]  2 × 4 vCPU/16 GB gp3 50 GB" in r.output and "scale out" in r.output
    puts = fake.calls("PUT", "*/clusters/*")
    assert len(puts) == 1
    assert puts[0].body["serviceGroups"] == [_group(["data", "index", "query"], 3), _group(["search"])]
    assert _keys(path) == ["data,index,query", "search"]


@pytest.mark.story("CAP-052", "AC2")
def test_group_cmd_ac2_file_updated_no_drift(fake, run, imported):
    path, _ = imported
    r = run("--auto-approve", "cluster", "group", "add", "nova-dev-01", "--services", "query,index", "--nodes", "2",
            "--cpu", "16", "--ram", "64", "--disk-size", "100")
    assert r.exit_code == 0, r.output
    added = file_clusters(path)[0]["serviceGroups"][1]
    assert added["services"] == ["index", "query"] and added["node"]["compute"] == {"cpu": 16, "ram": 64}
    assert added["node"]["disk"]["storage"] == 100
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output
    assert "already in sync" in run("sync").output


@pytest.mark.story("CAP-052", "AC3")
def test_group_cmd_ac3_add_rerun_noop(fake, run, imported):
    args = ["--auto-approve", "cluster", "group", "add", "nova-dev-01", "--services", "search", "--nodes", "2"]
    assert run(*args).exit_code == 0
    fake.reset_calls()
    r = run(*args)
    assert r.exit_code == 0 and "group search already exists on nova-dev-01; nothing to add" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-052", "AC3")
@pytest.mark.parametrize("args,code,msg", [
    (["--services", "data,index,query", "--nodes", "5"], 3,
     "group data,index,query already exists with 3 × 4/16\n[ACTION]: Change its node count with 'capellactl cluster scale nova-dev-01 --group data,index,query"),
    (["--services", "search", "--nodes", "25"], 3, "additional service groups allow 2–24 nodes"),
    (["--services", "cache"], 3, "unknown service 'cache'"),
])
def test_group_cmd_ac3_add_refused(fake, run, imported, args, code, msg):
    path, _ = imported
    before = path.read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "group", "add", "nova-dev-01", *args)
    assert r.exit_code == code and msg in r.output, r.output
    assert path.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-052", "AC3")
def test_group_cmd_ac3_add_refused_single_node(fake, run, imported):
    assert run("--auto-approve", "cluster", "create", "nova-ci-01", "--size", "dev").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "group", "add", "nova-ci-01", "--services", "search")
    assert r.exit_code == 3 and "singleNode clusters have exactly one service group" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-052", "AC4")
def test_group_cmd_ac4_remove_body(fake, run, three_groups):
    path, _ = three_groups
    r = run("--auto-approve", "cluster", "group", "remove", "nova-dev-01", "search")
    assert r.exit_code == 0, r.output
    assert "- serviceGroups[search]" in r.output
    puts = fake.calls("PUT", "*/clusters/*")
    assert len(puts) == 1 and [g["services"] for g in puts[0].body["serviceGroups"]] == \
        [["data", "index", "query"], ["index", "search"]]
    assert _keys(path) == ["data,index,query", "index,search"]


@pytest.mark.story("CAP-052", "AC4")
def test_group_cmd_ac4_remove_guards(fake, run, three_groups):
    path, _ = three_groups
    assert run("--auto-approve", "cluster", "group", "remove", "nova-dev-01", "search").exit_code == 0
    fake.reset_calls()
    before = path.read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "group", "remove", "nova-dev-01", "search,index")
    assert r.exit_code == 4 and "removes the last search nodes; pass --allow-service-removal" in r.output, r.output
    assert path.read_text(encoding="utf-8") == before and fake.writes() == []
    r = run("--auto-approve", "cluster", "group", "remove", "nova-dev-01", "index,search", "--allow-service-removal")
    assert r.exit_code == 0, r.output
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "group", "remove", "nova-dev-01", "data,index,query")
    assert r.exit_code == 4 and "the last group running data cannot be removed" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-052", "AC4")
def test_group_cmd_ac4_remove_memory_guard(fake, run, fake_stats_full):
    r = run("--auto-approve", "cluster", "group", "remove", "nova-dev-01", "data")
    assert r.exit_code == 4 and "scale-in blocked: buckets allocate" in r.output, r.output
    assert fake.writes() == []


@pytest.fixture
def fake_stats_full(fake, run, tmp_path):
    pid, cid = seed_healthy(fake)
    fake.clusters[cid]["body"]["serviceGroups"] = [_group(["data", "index", "query"], 3, 8, 32), _group(["data"], 3)]
    fake.cluster_total_memory_mb = 1000
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=900, replicas=1)
    assert run("import").exit_code == 0
    fake.reset_calls()
    return cid


@pytest.mark.story("CAP-052", "AC5")
def test_group_cmd_ac5_remove_missing_noop(fake, run, three_groups):
    r = run("--auto-approve", "cluster", "group", "remove", "nova-dev-01", "eventing")
    assert r.exit_code == 0, r.output
    assert "no service group 'eventing' (groups: data,index,query · search · index,search)" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-052", "AC6")
def test_group_cmd_ac6_turned_off_blocked(fake, run, imported):
    path, cid = imported
    fake.set_transition(cid, ["turnedOff"])
    before = path.read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "group", "add", "nova-dev-01", "--services", "search")
    assert r.exit_code == 4 and "turned off" in r.output, r.output
    assert path.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-052", "AC7")
def test_group_cmd_ac7_help_examples(run):
    for verb in ("list", "add", "remove"):
        r = run("cluster", "group", verb, "--help")
        assert r.exit_code == 0 and f"capellactl cluster group {verb} nova-prod-01" in r.output, verb
    r = run("help", "scaling")
    assert "capellactl cluster group add NAME --services search --nodes 2" in r.output


@pytest.mark.story("CAP-052", "AC3")
def test_group_cmd_ac3_add_refused_total_and_free_tier(fake, run, three_groups):
    path, _ = three_groups
    before = path.read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "group", "add", "nova-dev-01", "--services", "eventing", "--nodes", "24")
    assert r.exit_code == 3 and "a cluster can have at most 27 nodes (declared 31)" in r.output, r.output
    assert path.read_text(encoding="utf-8") == before and fake.writes() == []
    assert run("--auto-approve", "cluster", "create", "try-01", "--free-tier").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "group", "add", "try-01", "--services", "search")
    assert r.exit_code == 4 and "[ERROR]: free-tier clusters have 1 node and a fixed size" in r.output
    assert fake.writes() == []
