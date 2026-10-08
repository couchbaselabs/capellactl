"""CAP-031: drift report and apply --prune."""
from __future__ import annotations

import json

import pytest

from capellactl.cli import console
from tests.conftest import MINIMAL, seed_healthy

FILE = MINIMAL + """\
    buckets:
      - name: orders
        memoryAllocationInMb: 1024
        scopes:
          - name: inventory
            collections:
              - name: items
"""


def _drifted(fake):
    _, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=2048)  # changed: the file says 1024
    fake.seed_scope(cid, "orders", "inventory", {})  # missing: collection items
    fake.users["u-9"] = {"id": "u-9", "_cluster": cid, "name": "temp_admin", "access": [  # made by hand
        {"privileges": ["data_reader", "data_writer"], "resources": {"buckets": [{"name": "orders"}]}}]}
    return cid


@pytest.mark.story("CAP-031", "AC1")
def test_drift_ac1_three_groups(fake, run, write_config):
    _drifted(fake)
    write_config(FILE)
    fake.reset_calls()
    r = run("drift")
    assert r.exit_code == 0, r.output
    out = r.output
    assert out.index("Changed") < out.index("~ bucket nova-dev-01/orders") < out.index("Missing")
    assert "memoryAllocationInMb:  2048 → 1024" in out
    assert out.index("Missing") < out.index("+ collection nova-dev-01/orders/inventory/items") < out.index("Unmanaged")
    assert "credential nova-dev-01/temp_admin" in out[out.index("Unmanaged"):]
    assert "Drift: 1 changed, 1 missing, 1 unmanaged." in out
    assert fake.writes() == []


@pytest.mark.story("CAP-031", "AC2")
def test_drift_ac2_exit_code_and_json(fake, run, write_config):
    _drifted(fake)
    write_config(FILE)
    assert run("drift", "--detailed-exitcode").exit_code == 2
    js = json.loads(run("-o", "json", "drift").output)
    assert [a["key"] for a in js["changed"]] == ["nova-dev-01/orders"]
    assert [a["key"] for a in js["missing"]] == ["nova-dev-01/orders/inventory/items"]
    assert js["unmanaged"] == ["credential nova-dev-01/temp_admin"]
    assert run("--auto-approve", "apply", "--prune").exit_code == 0
    r = run("drift", "--detailed-exitcode")
    assert r.exit_code == 0 and "No drift: Capella matches capella.yaml." in r.output, r.output


@pytest.mark.story("CAP-031", "AC3")
def test_prune_ac3_children_only(fake, run, write_config):
    pid, cid = seed_healthy(fake)
    fake.seed_cluster(pid, "someone-else")
    fake.users["u-9"] = {"id": "u-9", "_cluster": cid, "name": "temp_admin", "access": [
        {"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders"}]}}]}
    fake.cidrs["cidr-9"] = {"id": "cidr-9", "_cluster": cid, "cidr": "192.0.2.0/24", "status": "active",
                            "type": "permanent"}
    write_config(MINIMAL)
    r = run("--auto-approve", "apply", "--prune")
    assert r.exit_code == 0, r.output
    assert "  - credential nova-dev-01/temp_admin" in r.output and "  - allowed-cidr nova-dev-01/192.0.2.0/24" in r.output
    assert "cluster someone-else  (not pruned: clusters are never pruned)" in r.output
    assert sorted(c.method for c in fake.writes()) == ["DELETE", "DELETE"]
    assert any(c["body"]["name"] == "someone-else" for c in fake.clusters.values())


@pytest.mark.story("CAP-031", "AC4")
def test_prune_ac4_protection_and_confirmation(fake, run, write_config, monkeypatch):
    _, cid = seed_healthy(fake, deletionProtection=True)
    fake.seed_bucket(cid, "scratch")
    write_config(MINIMAL)
    r = run("--auto-approve", "apply", "--prune")
    assert r.exit_code == 4 and "deletion protection is on for nova-dev-01" in r.output
    assert fake.writes() == []
    fake.clusters[cid]["body"]["deletionProtection"] = False
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("apply", "--prune", input="wrong\n")
    assert "Type the bucket name to confirm deletion of nova-dev-01/scratch" in r.output
    assert fake.writes() == []
    r = run("apply", "--prune", input="scratch\ny\n")
    assert r.exit_code == 0 and [c.method for c in fake.writes()] == ["DELETE"], r.output


@pytest.mark.story("CAP-031", "AC5")
def test_drift_ac5_system_objects_excluded(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=1024)  # has _default and _system scopes
    write_config(MINIMAL + "    buckets:\n      - name: orders\n        memoryAllocationInMb: 1024\n")
    r = run("drift")
    assert "_default" not in r.output and "_system" not in r.output
    assert "No drift" in r.output, r.output
