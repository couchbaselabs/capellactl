"""CAP-024: delete a bucket deliberately and safely."""
from __future__ import annotations

import pytest

from capellactl.cli import console
from tests.conftest import MINIMAL, file_clusters, seed_healthy

ORDERS = "    buckets:\n      - name: orders\n        memoryAllocationInMb: 1024\n"
STATS = {"itemCount": 1204, "opsPerSecond": 0, "diskUsedInMib": 900, "memoryUsedInMib": 412}


@pytest.fixture
def orders(fake, write_config):
    """Cluster nova-dev-01 with bucket orders (1,204 items) in Capella and in capella.yaml."""
    pid, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=1024, stats=STATS)
    write_config(MINIMAL + ORDERS)
    return pid, cid


def _user(fake, cid, name, buckets):
    access = [{"privileges": ["data_reader"], "resources": {"buckets": [{"name": b} for b in buckets]}}]
    fake.users[f"u-{name}"] = {"id": f"u-{name}", "_cluster": cid, "name": name, "access": access}


@pytest.mark.story("CAP-024", "AC1")
def test_bucket_delete_ac1_confirm_and_delete(fake, run, orders, tmp_path, monkeypatch):
    pid, cid = orders
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("bucket", "delete", "nova-dev-01", "orders", input="orders\n")
    assert r.exit_code == 0, r.output
    assert "orders · 1,204 items · 412 MB used" in r.output
    assert "deleted bucket nova-dev-01/orders" in r.output
    assert [(c.method, c.path) for c in fake.writes()] == [
        ("DELETE", f"/v4/organizations/org-1/projects/{pid}/clusters/{cid}/buckets/b3JkZXJz")]
    assert "buckets" not in file_clusters(tmp_path / "capella.yaml")[0]


@pytest.mark.story("CAP-024", "AC1")
def test_bucket_delete_ac1_wrong_name_cancels(fake, run, orders, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("bucket", "delete", "nova-dev-01", "orders", input="order\n")
    assert r.exit_code == 0 and "Cancelled; nothing was deleted." in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-024", "AC1")
def test_bucket_delete_ac1_non_interactive_needs_auto_approve(fake, run, orders):
    r = run("bucket", "delete", "nova-dev-01", "orders")
    assert r.exit_code == 1 and "--auto-approve" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-024", "AC2")
def test_bucket_delete_ac2_protection_blocks(fake, run, orders):
    _, cid = orders
    fake.clusters[cid]["body"]["deletionProtection"] = True
    r = run("--auto-approve", "bucket", "delete", "nova-dev-01", "orders")
    assert r.exit_code == 4
    assert "deletion protection is on for nova-dev-01; run 'capellactl cluster protect nova-dev-01 --off' first" \
        in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-024", "AC3")
def test_bucket_delete_ac3_lists_dependent_credentials(fake, run, orders, monkeypatch):
    _, cid = orders
    _user(fake, cid, "reporting_ro", ["orders"])
    _user(fake, cid, "orders_app", ["orders", "events"])
    _user(fake, cid, "events_app", ["events"])
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("bucket", "delete", "nova-dev-01", "orders", input="orders\n")
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    i = lines.index("  These credentials lose access to this bucket:")
    assert lines[i + 1:i + 3] == ["    orders_app", "    reporting_ro"]
    assert "events_app" not in r.output
    assert "deleted bucket nova-dev-01/orders" in r.output


@pytest.mark.story("CAP-024", "AC4")
def test_bucket_delete_ac4_removed_from_file_not_deleted(fake, run, orders, write_config):
    write_config()  # orders no longer declared
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "bucket" not in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-024", "AC4")
def test_bucket_delete_ac4_prune_deletes(fake, run, orders, write_config, monkeypatch):
    pid, cid = orders
    write_config()
    r = run("plan")
    assert "- bucket" not in r.output
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("apply", "--prune", input="orders\ny\n")
    assert r.exit_code == 0, r.output
    assert "  - bucket nova-dev-01/orders" in r.output
    assert "orders · 1,204 items · 412 MB used" in r.output
    assert [(c.method, c.path) for c in fake.writes()] == [
        ("DELETE", f"/v4/organizations/org-1/projects/{pid}/clusters/{cid}/buckets/b3JkZXJz")]


@pytest.mark.story("CAP-024", "AC4")
def test_bucket_delete_ac4_prune_respects_protection(fake, run, orders, write_config):
    _, cid = orders
    fake.clusters[cid]["body"]["deletionProtection"] = True
    write_config()
    r = run("--auto-approve", "apply", "--prune")
    assert r.exit_code == 4
    assert "! bucket nova-dev-01/orders  deletion protection is on for nova-dev-01" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-024", "AC5")
def test_bucket_delete_ac5_rerun_noop(fake, run, orders):
    assert run("--auto-approve", "bucket", "delete", "nova-dev-01", "orders").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "bucket", "delete", "nova-dev-01", "orders")
    assert r.exit_code == 0
    assert "bucket nova-dev-01/orders not found, nothing to do" in r.output
    assert fake.writes() == []
