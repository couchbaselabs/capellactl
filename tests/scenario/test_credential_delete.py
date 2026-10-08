"""CAP-029: delete a database credential (command, and apply --prune)."""
from __future__ import annotations

import pytest

from capellactl.cli import console
from tests.conftest import MINIMAL, file_clusters, seed_healthy
from tests.scenario.helpers import ORDERS_BUCKET, USERS, seed_user

READ_ORDERS = [{"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders"}]}}]
REPORTING = """\
    databaseCredentials:
      - name: reporting_ro
        access:
          - privileges: [read]
            resources: { buckets: [ { name: orders } ] }
"""


@pytest.fixture
def cluster(fake):
    pid, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=100)
    fake.seed_scope(cid, "orders", "inventory", {"items": 0, "suppliers": 0})  # as ORDERS_BUCKET declares
    return pid, cid


@pytest.mark.story("CAP-029", "AC1")
def test_credential_delete_ac1_delete(fake, run, write_config, cluster, tmp_path, monkeypatch):
    pid, cid = cluster
    uid = seed_user(fake, cid, "reporting_ro", READ_ORDERS)
    write_config(MINIMAL + ORDERS_BUCKET + REPORTING)
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("credential", "delete", "nova-dev-01", "reporting_ro", input="n\n")
    assert "  - credential nova-dev-01/reporting_ro  read · orders" in r.output and "Cancelled" in r.output
    assert fake.writes() == []
    r = run("credential", "delete", "nova-dev-01", "reporting_ro", input="y\n")
    assert r.exit_code == 0, r.output
    assert [(c.method, c.path) for c in fake.writes()] == [("DELETE", USERS.format(pid=pid, cid=cid) + f"/{uid}")]
    assert "deleted credential nova-dev-01/reporting_ro" in r.output
    assert "databaseCredentials" not in file_clusters(tmp_path / "capella.yaml")[0]


@pytest.mark.story("CAP-029", "AC2")
def test_credential_delete_ac2_secret_file_kept(fake, run, write_config, cluster, tmp_path):
    _, cid = cluster
    seed_user(fake, cid, "reporting_ro", READ_ORDERS)
    write_config(MINIMAL + ORDERS_BUCKET + REPORTING)
    secret = tmp_path / ".capellactl" / "credentials" / "nova-dev-01.reporting_ro.json"
    secret.parent.mkdir(parents=True)
    secret.write_text("{}")
    r = run("--auto-approve", "credential", "delete", "nova-dev-01", "reporting_ro")
    assert r.exit_code == 0, r.output
    assert secret.exists()
    assert "local secret file kept: " in r.output and "nova-dev-01.reporting_ro.json (delete it if no longer needed)" \
        in r.output


@pytest.mark.story("CAP-029", "AC3")
def test_credential_delete_ac3_prune_only(fake, run, write_config, cluster):
    pid, cid = cluster
    uid = seed_user(fake, cid, "reporting_ro", READ_ORDERS)
    seed_user(fake, cid, "dba", [], userRoles=[{"name": "admin"}])  # advanced: never pruned by 1.0
    write_config(MINIMAL + ORDERS_BUCKET)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert fake.writes() == []
    r = run("--auto-approve", "apply", "--prune")
    assert r.exit_code == 0, r.output
    assert [(c.method, c.path) for c in fake.writes()] == [("DELETE", USERS.format(pid=pid, cid=cid) + f"/{uid}")]
    assert "  - credential nova-dev-01/reporting_ro" in r.output
    assert "credential nova-dev-01/dba  (advanced credential: not managed by capellactl 1.0, left unchanged)" in r.output


@pytest.mark.story("CAP-029", "AC4")
def test_credential_delete_ac4_rerun_noop(fake, run, write_config, cluster):
    _, cid = cluster
    seed_user(fake, cid, "reporting_ro", READ_ORDERS)
    write_config(MINIMAL + ORDERS_BUCKET + REPORTING)
    assert run("--auto-approve", "credential", "delete", "nova-dev-01", "reporting_ro").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "credential", "delete", "nova-dev-01", "reporting_ro")
    assert r.exit_code == 0, r.output
    assert "credential nova-dev-01/reporting_ro not found, nothing to do" in r.output
    assert fake.writes() == []
