"""CAP-023: ensure bucket (create & update), through apply and the bucket commands."""
from __future__ import annotations

import pytest

from tests.conftest import MINIMAL, file_clusters, seed_healthy

ORDERS = """\
    buckets:
      - name: orders
        storageBackend: magma
        memoryAllocationInMb: 1024
        durabilityLevel: majority
"""


def _orders(fake, cid, **fields):
    base = {"storageBackend": "magma", "memoryAllocationInMb": 1024, "durabilityLevel": "majority"}
    return fake.seed_bucket(cid, "orders", **{**base, **fields})


@pytest.mark.story("CAP-023", "AC1")
def test_bucket_ac1_create_body(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL + ORDERS)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "  + bucket nova-dev-01/orders  couchbase · magma · 1024 MB · 1 replica · durability majority" in r.output
    posts = fake.calls("POST", f"*/clusters/{cid}/buckets")
    assert len(posts) == 1
    assert posts[0].body == {"name": "orders", "type": "couchbase", "storageBackend": "magma",
                             "memoryAllocationInMb": 1024, "bucketConflictResolution": "seqno",
                             "durabilityLevel": "majority", "replicas": 1, "flushEnabled": False,
                             "timeToLiveInSeconds": 0}
    assert "flush" not in posts[0].body


@pytest.mark.story("CAP-023", "AC1")
def test_bucket_cli_ac1_create_records_and_applies(fake, run, write_config, tmp_path):
    _, cid = seed_healthy(fake)
    write_config()
    r = run("--auto-approve", "bucket", "create", "nova-dev-01", "orders", "--memory", "1024",
            "--storage-backend", "magma", "--durability", "majority")
    assert r.exit_code == 0, r.output
    assert "+ bucket nova-dev-01/orders  couchbase · magma · 1024 MB · 1 replica · durability majority" in r.output
    assert file_clusters(tmp_path / "capella.yaml")[0]["buckets"] == [
        {"name": "orders", "storageBackend": "magma", "memoryAllocationInMb": 1024, "durabilityLevel": "majority"}]
    assert len(fake.calls("POST", f"*/clusters/{cid}/buckets")) == 1
    fake.reset_calls()
    assert "Plan: 0 to add, 0 to change, 0 to delete, 0 blocked." in run("plan").output
    assert fake.writes() == []


@pytest.mark.story("CAP-038", "AC8")
def test_bucket_cli_ac8_rejected_create_restores_file(fake, run, write_config, tmp_path):
    seed_healthy(fake)
    write_config()
    before = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    fake.fail_next("POST", "*/buckets", 422)
    r = run("--auto-approve", "bucket", "create", "nova-dev-01", "orders", "--memory", "1024")
    assert r.exit_code == 1 and "capella.yaml was restored" in r.output, r.output
    assert (tmp_path / "capella.yaml").read_text(encoding="utf-8") == before


@pytest.mark.story("CAP-023", "AC1")
def test_bucket_cli_ac1_create_already_in_file_refused(fake, run, write_config):
    _, cid = seed_healthy(fake)
    _orders(fake, cid)
    write_config(MINIMAL + ORDERS)
    r = run("--auto-approve", "bucket", "create", "nova-dev-01", "orders", "--memory", "512")
    assert r.exit_code == 4
    assert "bucket update nova-dev-01 orders" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-023", "AC1")
def test_bucket_cli_ac1_create_finishes_recorded_bucket(fake, run, write_config, tmp_path):
    """In the file but not in Capella (an earlier create did not finish): create completes it instead of looping
    between 'already in capella.yaml' and update, which cannot set storage backend or type."""
    _, cid = seed_healthy(fake)
    write_config(MINIMAL + ORDERS)
    r = run("--auto-approve", "bucket", "create", "nova-dev-01", "orders", "--memory", "256",
            "--storage-backend", "couchstore")
    assert r.exit_code == 0, r.output
    assert "not in Capella yet (an earlier run did not finish); creating it now" in r.output
    assert file_clusters(tmp_path / "capella.yaml")[0]["buckets"] == [
        {"name": "orders", "storageBackend": "couchstore", "memoryAllocationInMb": 256, "durabilityLevel": "majority"}]
    posts = fake.calls("POST", f"*/clusters/{cid}/buckets")
    assert len(posts) == 1 and posts[0].body["storageBackend"] == "couchstore"
    fake.reset_calls()
    assert "Plan: 0 to add, 0 to change, 0 to delete, 0 blocked." in run("plan").output


@pytest.mark.story("CAP-023", "AC2")
def test_bucket_ac2_defaults_noop(fake, run, write_config):
    _, cid = seed_healthy(fake)
    _orders(fake, cid, flush=False)  # observed defaults equal the file's defaults; deprecated flush is read too
    del fake.buckets[(cid, "b3JkZXJz")]["flushEnabled"]
    write_config(MINIMAL + ORDERS)
    r = run("plan")
    assert r.exit_code == 0, r.output
    assert "  = bucket nova-dev-01/orders" in r.output
    assert "Plan: 0 to add, 0 to change, 0 to delete, 0 blocked." in r.output
    assert run("--auto-approve", "apply").exit_code == 0
    assert fake.writes() == []


@pytest.mark.story("CAP-023", "AC3")
def test_bucket_ac3_update_full_body(fake, run, write_config):
    _, cid = seed_healthy(fake)
    bid = _orders(fake, cid, priority=3)  # priority is not in the file: the PUT keeps the observed value
    write_config(MINIMAL + ORDERS.replace("1024", "2048"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    i = lines.index("  ~ bucket nova-dev-01/orders")
    assert lines[i + 1] == "      memoryAllocationInMb:  1024 → 2048"
    assert not lines[i + 2].startswith("      ")
    puts = fake.calls("PUT", f"*/buckets/{bid}")
    assert len(puts) == 1
    # Every updatable field Capella reported is sent back unchanged (enableCrossClusterVersioning included)
    assert puts[0].body == {"memoryAllocationInMb": 2048, "durabilityLevel": "majority", "replicas": 1,
                            "timeToLiveInSeconds": 0, "flushEnabled": False, "priority": 3,
                            "enableCrossClusterVersioning": False}


@pytest.mark.story("CAP-023", "AC3")
def test_bucket_cli_ac3_update_records_and_applies(fake, run, write_config, tmp_path):
    _, cid = seed_healthy(fake)
    bid = _orders(fake, cid)
    write_config(MINIMAL + ORDERS)
    r = run("--auto-approve", "bucket", "update", "nova-dev-01", "orders", "--memory", "2048")
    assert r.exit_code == 0, r.output
    assert "memoryAllocationInMb:  1024 → 2048" in r.output
    assert file_clusters(tmp_path / "capella.yaml")[0]["buckets"][0]["memoryAllocationInMb"] == 2048
    assert fake.buckets[(cid, bid)]["memoryAllocationInMb"] == 2048


@pytest.mark.story("CAP-023", "AC3")
def test_bucket_cli_ac3_update_not_in_file(fake, run, write_config):
    seed_healthy(fake)
    write_config()
    r = run("--auto-approve", "bucket", "update", "nova-dev-01", "orders", "--memory", "2048")
    assert r.exit_code == 3
    assert "bucket create nova-dev-01 orders" in r.output


@pytest.mark.story("CAP-023", "AC4")
@pytest.mark.parametrize(("field", "before", "after"), [
    ("type", "ephemeral", "couchbase"),
    ("storageBackend", "couchstore", "magma"),
    ("vbuckets", 128, 1024),
    ("bucketConflictResolution", "lww", "seqno"),
    ("evictionPolicy", "valueOnly", "fullEviction"),
])
def test_bucket_ac4_immutable_blocked(fake, run, write_config, field, before, after):
    _, cid = seed_healthy(fake)
    _orders(fake, cid, **{field: before})
    extra = {"type": "", "storageBackend": "", "bucketConflictResolution": "",
             "vbuckets": "        vbuckets: 1024\n", "evictionPolicy": "        evictionPolicy: fullEviction\n"}[field]
    write_config(MINIMAL + ORDERS + extra)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4, r.output
    assert (f"  ! bucket nova-dev-01/orders  {field}: {before} → {after}  BLOCKED (immutable; create a new bucket "
            "and migrate data)") in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-023", "AC6")
def test_bucket_ac6_memory_preflight_blocks(fake, run, write_config):
    seed_healthy(fake)
    fake.cluster_total_memory_mb = 512
    write_config(MINIMAL + ORDERS)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4, r.output
    assert ("  ! bucket nova-dev-01/orders  needs 1024 MB but the cluster has 512 MB free; scale out (CAP-015) or "
            "reduce memoryAllocationInMb") in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-023", "AC6")
def test_bucket_ac6_memory_preflight_sums_new_buckets(fake, run, write_config):
    seed_healthy(fake)
    fake.cluster_total_memory_mb = 1500
    write_config(MINIMAL + ORDERS + "      - name: events\n        memoryAllocationInMb: 1024\n")
    r = run("plan")
    assert r.exit_code == 4
    assert "  + bucket nova-dev-01/orders" in r.output
    assert "  ! bucket nova-dev-01/events  needs 1024 MB but the cluster has 476 MB free" in r.output


@pytest.mark.story("CAP-023", "AC6")
def test_bucket_ac6_memory_increase_preflight(fake, run, write_config):
    _, cid = seed_healthy(fake)
    _orders(fake, cid)
    fake.cluster_total_memory_mb = 1536  # 512 MB free
    write_config(MINIMAL + ORDERS.replace("1024", "2048"))
    r = run("plan")
    assert r.exit_code == 4
    assert "needs 1024 MB but the cluster has 512 MB free" in r.output


@pytest.mark.story("CAP-023", "AC6")
def test_bucket_ac6_replica_preflight_blocks(fake, run, write_config):
    seed_healthy(fake)  # 3 data nodes: maxReplicas 2
    write_config(MINIMAL + ORDERS + "        replicas: 3\n")
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4, r.output
    assert ("  ! bucket nova-dev-01/orders  replicas: 3 but the cluster supports at most 2; scale out (CAP-015) or "
            "reduce replicas") in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-023", "AC7")
def test_bucket_ac7_replica_change_note(fake, run, write_config):
    _, cid = seed_healthy(fake)
    _orders(fake, cid)
    write_config(MINIMAL + ORDERS + "        replicas: 2\n")
    r = run("plan")
    assert r.exit_code == 0, r.output
    assert "  ~ bucket nova-dev-01/orders  note: the new replica count takes full effect after a rebalance" in r.output
    assert "      replicas:  1 → 2" in r.output


@pytest.mark.story("CAP-023", "AC8")
def test_bucket_ac8_rerun_zero_writes(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL + ORDERS + "        enableCrossClusterVersioning: true\n        priority: 2\n")
    assert run("--auto-approve", "apply").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "No changes" in r.output
    assert fake.writes() == []


def test_bucket_list_and_get(fake, run, write_config):
    _, cid = seed_healthy(fake)
    _orders(fake, cid, stats={"itemCount": 1204, "memoryUsedInMib": 412, "diskUsedInMib": 900})
    fake.seed_bucket(cid, "events")
    write_config(MINIMAL + ORDERS)
    r = run("bucket", "list", "nova-dev-01")
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0].split() == ["S.NO", "NAME", "TYPE", "STORAGE", "MEMORY", "MB", "REPLICAS", "DURABILITY", "TTL", "ITEMS",
                                "IN", "FILE"]
    assert lines[1].split() == ["1", "orders", "couchbase", "magma", "1024", "1", "majority", "0", "1,204", "yes"]
    assert lines[2].split()[-1] == "-"
    r = run("bucket", "get", "nova-dev-01", "orders")
    assert r.exit_code == 0 and "storageBackend" in r.output and "items: 1,204" in r.output
    assert run("bucket", "get", "nova-dev-01", "nope").exit_code == 1
    assert fake.writes() == []
