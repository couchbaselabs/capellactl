"""CAP-023/024 on free-tier clusters (…/buckets/freeTier endpoints) and on single-node clusters (0 replicas)."""
from __future__ import annotations

import pytest

from tests.conftest import file_clusters

REGION = {"cloudProvider": {"type": "aws", "region": "us-east-2", "cidr": "10.0.0.0/23"}}
GROUP_1 = [{"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
            "numOfNodes": 1, "services": ["data", "index", "query"]}]


@pytest.fixture
def free(fake, run, tmp_path):
    """Imported capella.yaml with the free-tier cluster nova-dev (one data node: maxReplicas 0)."""
    pid = fake.seed_project("demo")
    cid = fake.seed_free_cluster(pid, "nova-dev", **REGION)
    assert run("import").exit_code == 0
    fake.reset_calls()
    return pid, cid


def _free_path(pid, cid, bid=""):
    return f"/v4/organizations/org-1/projects/{pid}/clusters/{cid}/buckets/freeTier" + (f"/{bid}" if bid else "")


@pytest.mark.story("CAP-023", "AC1")
def test_bucket_free_ac1_create_uses_free_tier_endpoint(fake, run, free, tmp_path):
    pid, cid = free
    r = run("--auto-approve", "bucket", "create", "nova-dev", "orders", "--memory", "100")
    assert r.exit_code == 0, r.output
    assert "  + bucket nova-dev/orders  free tier · 100 MB" in r.output
    assert [(c.method, c.path, c.body) for c in fake.writes()] == [
        ("POST", _free_path(pid, cid), {"name": "orders", "memoryAllocationInMb": 100})]
    assert file_clusters(tmp_path / "capella.yaml")[0]["buckets"] == [{"name": "orders", "memoryAllocationInMb": 100}]
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output  # AC8 on the free tier
    assert fake.writes() == []


@pytest.mark.story("CAP-023", "AC5")
def test_bucket_free_ac5_other_settings_refused(fake, run, free):
    r = run("--auto-approve", "bucket", "create", "nova-dev", "orders", "--memory", "100", "--storage-backend", "magma",
            "--durability", "majority")
    assert r.exit_code == 3
    assert ("nova-dev (project demo) is a free-tier cluster: Capella chooses its bucket settings, so "
            "--storage-backend, --durability cannot be set. Only --memory can be set.") in r.output
    assert "Try: capellactl bucket create nova-dev orders --memory 100" in r.output
    assert "line " not in r.output and "buckets[0]" not in r.output  # no YAML path of an unsaved file
    assert run("--auto-approve", "bucket", "create", "nova-dev", "orders", "--memory", "100").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "bucket", "update", "nova-dev", "orders", "--replicas", "2")
    assert r.exit_code == 3
    assert "so --replicas cannot be set. Only --memory and --cross-cluster-versioning can be set." in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-023", "AC5")
def test_bucket_free_ac5_interactive_update_asks_memory_only(fake, run, free, monkeypatch):
    from capellactl.cli import console as console_mod

    assert run("--auto-approve", "bucket", "create", "nova-dev", "orders", "--memory", "100").exit_code == 0
    monkeypatch.setattr(console_mod, "is_interactive", lambda: True)
    r = run("--auto-approve", "bucket", "update", "nova-dev", "orders", input="200\n")
    assert r.exit_code == 0, r.output
    assert "Memory (MB)" in r.output and "Replicas" not in r.output and "Durability" not in r.output


@pytest.mark.story("CAP-023", "AC3")
def test_bucket_free_ac3_update_memory(fake, run, free):
    pid, cid = free
    assert run("--auto-approve", "bucket", "create", "nova-dev", "orders", "--memory", "100").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "bucket", "update", "nova-dev", "orders", "--memory", "200")
    assert r.exit_code == 0, r.output
    assert "memoryAllocationInMb:  100 → 200" in r.output
    assert [(c.method, c.path, c.body) for c in fake.writes()] == [
        ("PUT", _free_path(pid, cid, "b3JkZXJz"), {"memoryAllocationInMb": 200, "enableCrossClusterVersioning": False})]


@pytest.mark.story("CAP-024", "AC1")
def test_bucket_free_delete_and_list(fake, run, free):
    pid, cid = free
    fake.seed_bucket(cid, "orders", stats={"itemCount": 7, "memoryUsedInMib": 12})
    r = run("bucket", "list", "nova-dev")
    assert r.exit_code == 0 and r.output.splitlines()[1].split()[:2] == ["1", "orders"]
    r = run("--auto-approve", "bucket", "delete", "nova-dev", "orders")
    assert r.exit_code == 0, r.output
    assert "orders · 7 items · 12 MB used" in r.output
    assert [(c.method, c.path) for c in fake.writes()] == [("DELETE", _free_path(pid, cid, "b3JkZXJz"))]


def test_import_free_tier_buckets_round_trip(fake, run, tmp_path):
    pid = fake.seed_project("demo")
    cid = fake.seed_free_cluster(pid, "nova-dev", **REGION)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=200)
    assert run("import").exit_code == 0
    assert file_clusters(tmp_path / "capella.yaml")[0]["buckets"] == [{"name": "orders", "memoryAllocationInMb": 200}]
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0, r.output


@pytest.mark.story("CAP-023", "AC6")
def test_bucket_ac6_single_node_uses_zero_replicas(fake, run, write_config):
    """Capella rejects any replica count but 0 on single-node clusters (422: 'Single-node clusters only support a
    replica count of 0')."""
    from tests.conftest import MINIMAL

    pid = fake.seed_project("nova-dev", description="Nova development environment")
    fake.seed_cluster(pid, "nova-dev-01", description="Nova development cluster", configurationType="singleNode",
                      availability={"type": "single"}, serviceGroups=GROUP_1)
    cfg = (MINIMAL.replace("availability: { type: multi }", "availability: { type: single }\n    configurationType: singleNode")
           .replace("numOfNodes: 3", "numOfNodes: 1"))
    write_config(cfg + "    buckets:\n      - name: orders\n        memoryAllocationInMb: 100\n")
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "+ bucket nova-dev-01/orders  couchbase · 100 MB · 0 replicas · durability none" in r.output
    assert "note:" not in r.output
    assert fake.calls("POST", "*/buckets")[0].body["replicas"] == 0
    write_config(cfg + "    buckets:\n      - name: orders\n        memoryAllocationInMb: 100\n        replicas: 1\n")
    r = run("plan")
    assert r.exit_code == 3
    assert "single-node clusters only support replicas: 0" in r.output
    write_config(MINIMAL + "    buckets:\n      - name: orders\n        memoryAllocationInMb: 100\n        replicas: 0\n")
    r = run("plan")
    assert r.exit_code == 3 and "replicas: 0 is only for single-node clusters; use 1, 2 or 3" in r.output

