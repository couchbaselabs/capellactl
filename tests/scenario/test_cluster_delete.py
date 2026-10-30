"""CAP-014: delete a cluster safely and wait until it is gone."""
from __future__ import annotations

import pytest

from capellactl.cli import console
from tests.conftest import MINIMAL, file_clusters, seed_healthy

PATH = "/v4/organizations/org-1/projects/{pid}/clusters/{cid}"


@pytest.fixture
def cluster(fake, write_config):
    """nova-dev-01, healthy and unprotected, in Capella and in capella.yaml."""
    pid, cid = seed_healthy(fake)
    write_config(MINIMAL)
    return pid, cid


def _deletes(fake):
    return [(c.method, c.path, c.query) for c in fake.writes()]


@pytest.mark.story("CAP-014", "AC1")
def test_cluster_delete_ac1_delete_and_wait(fake, run, cluster, tmp_path, monkeypatch):
    pid, cid = cluster
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "delete", "nova-dev-01", input="nova-dev-01\n")
    assert r.exit_code == 0, r.output
    assert "  - cluster nova-dev-01  aws us-east-1 · 3 nodes · 0 buckets" in r.output
    assert "snapshot backups are kept" in r.output
    assert "cluster nova-dev-01: deleted" in r.output
    assert "deleted cluster nova-dev-01 (snapshot backups retained)" in r.output
    assert _deletes(fake) == [("DELETE", PATH.format(pid=pid, cid=cid), {"retainsnapshotbackups": ["true"]})]
    assert cid not in fake.clusters  # waited until GET returned 404
    assert file_clusters(tmp_path / "capella.yaml") == []


@pytest.mark.story("CAP-014", "AC1")
def test_cluster_delete_ac1_wrong_name_cancels(fake, run, cluster, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "delete", "nova-dev-01", input="nova-dev\n")
    assert r.exit_code == 0 and "Cancelled; nothing was deleted." in r.output
    assert fake.writes() == []
    monkeypatch.setattr(console, "is_interactive", lambda: False)
    r = run("cluster", "delete", "nova-dev-01")
    assert r.exit_code == 1 and "--auto-approve" in r.output and fake.writes() == []


@pytest.mark.story("CAP-014", "AC2")
def test_cluster_delete_ac2_discard_snapshots(fake, run, cluster, monkeypatch):
    pid, cid = cluster
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "delete", "nova-dev-01", "--discard-snapshots", input="nova-dev-01\n")
    assert r.exit_code == 0, r.output
    assert "snapshot backups will be deleted" in r.output
    assert "deleted cluster nova-dev-01 (snapshot backups deleted)" in r.output
    assert _deletes(fake) == [("DELETE", PATH.format(pid=pid, cid=cid), {"retainsnapshotbackups": ["false"]})]


@pytest.mark.story("CAP-014", "AC3")
def test_cluster_delete_ac3_protected_blocked(fake, run, cluster):
    _, cid = cluster
    fake.clusters[cid]["body"]["deletionProtection"] = True
    r = run("--auto-approve", "cluster", "delete", "nova-dev-01")
    assert r.exit_code == 4
    assert "deletion protection is on for nova-dev-01" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-014", "AC3")
def test_cluster_delete_ac3_ambiguous_blocked(fake, run, cluster):
    pid, _ = cluster
    fake.seed_cluster(pid, "nova-dev-01")
    r = run("--auto-approve", "cluster", "delete", "nova-dev-01")
    assert r.exit_code == 4
    assert "2 clusters are named nova-dev-01" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-014", "AC3")
def test_cluster_delete_ac3_lists_buckets_in_confirmation(fake, run, cluster, monkeypatch):
    _, cid = cluster
    fake.seed_bucket(cid, "orders")
    fake.seed_bucket(cid, "events")
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "delete", "nova-dev-01", input="nova-dev-01\n")
    assert r.exit_code == 0, r.output
    assert "· 2 buckets" in r.output
    assert "buckets deleted with the cluster: events, orders" in r.output
    assert [c.method for c in fake.writes()] == ["DELETE"]  # not blocked; no separate bucket deletes


@pytest.mark.story("CAP-014", "AC4")
def test_cluster_delete_ac4_destroying_waits_only(fake, run, cluster, tmp_path):
    _, cid = cluster
    fake.clusters[cid]["deleted_at"] = fake.clock.monotonic() + 120  # someone else started the delete
    r = run("--auto-approve", "cluster", "delete", "nova-dev-01")
    assert r.exit_code == 0, r.output
    assert "cluster nova-dev-01 is already being deleted; waiting until it is gone" in r.output
    assert "deleted cluster nova-dev-01" in r.output
    assert fake.writes() == []
    assert file_clusters(tmp_path / "capella.yaml") == []


@pytest.mark.story("CAP-014", "AC4")
def test_cluster_delete_ac4_absent_noop(fake, run, write_config):
    fake.seed_project("nova-dev")
    write_config(MINIMAL)
    r = run("--auto-approve", "cluster", "delete", "nova-dev-01")
    assert r.exit_code == 0
    assert "cluster nova-dev-01 not found, nothing to do" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-014", "AC5")
def test_cluster_delete_ac5_destroy_failed(fake, run, cluster, tmp_path):
    _, cid = cluster
    fake.fail_destroy(cid)
    r = run("--auto-approve", "cluster", "delete", "nova-dev-01")
    assert r.exit_code == 1
    assert "[ERROR]: Failed: cluster nova-dev-01 entered destroyFailed\n[ACTION]: Open the cluster's activity log in the Capella UI" in r.output
    assert len(file_clusters(tmp_path / "capella.yaml")) == 1  # still there: it was not deleted


@pytest.mark.story("CAP-014", "AC6")
def test_cluster_delete_ac6_mentions_schedule(fake, run, cluster):
    pid, cid = cluster
    fake.schedules[cid] = {"timezone": "US/Pacific", "days": [], "activationStatus": "active"}
    r = run("--auto-approve", "cluster", "delete", "nova-dev-01")
    assert r.exit_code == 0, r.output
    assert "hibernation schedule (US/Pacific) is deleted with the cluster" in r.output
    assert _deletes(fake) == [("DELETE", PATH.format(pid=pid, cid=cid), {"retainsnapshotbackups": ["true"]})]


@pytest.mark.story("CAP-014", "AC7")
def test_cluster_delete_ac7_rerun_noop(fake, run, cluster):
    assert run("--auto-approve", "cluster", "delete", "nova-dev-01").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "delete", "nova-dev-01")
    assert r.exit_code == 0
    assert "cluster nova-dev-01 not found, nothing to do" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-014", "AC1")
def test_cluster_delete_no_wait_then_rerun_waits(fake, run, cluster, tmp_path):
    r = run("--auto-approve", "--no-wait", "cluster", "delete", "nova-dev-01")
    assert r.exit_code == 0 and "is being deleted (--no-wait)" in r.output
    assert len(file_clusters(tmp_path / "capella.yaml")) == 1
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "delete", "nova-dev-01")
    assert r.exit_code == 0 and "deleted cluster nova-dev-01" in r.output
    assert fake.writes() == [] and file_clusters(tmp_path / "capella.yaml") == []
