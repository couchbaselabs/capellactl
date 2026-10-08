"""CAP-026: delete scopes & collections deliberately."""
from __future__ import annotations

import pytest

from capellactl.cli import console
from tests.conftest import MINIMAL, file_clusters, seed_healthy
from tests.scenario.helpers import seed_user

BILLING = """\
    buckets:
      - name: orders
        memoryAllocationInMb: 100
        scopes:
          - name: billing
            collections:
              - name: invoices
              - name: refunds
"""
B = "/v4/organizations/org-1/projects/{pid}/clusters/{cid}/buckets/b3JkZXJz"


@pytest.fixture
def billing(fake, write_config):
    """Scope orders/billing with collections invoices and refunds, in Capella and in capella.yaml."""
    pid, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=100)
    fake.seed_scope(cid, "orders", "billing", {"invoices": 0, "refunds": 0})
    write_config(MINIMAL + BILLING)
    return pid, cid


def _deletes(fake, pid, cid):
    return [c.path.replace(B.format(pid=pid, cid=cid), "") for c in fake.writes() if c.method == "DELETE"]


def _grant(scope, collections=None):
    s = {"name": scope, **({"collections": collections} if collections else {})}
    return [{"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders", "scopes": [s]}]}}]


@pytest.mark.story("CAP-026", "AC1")
def test_collection_delete_ac1_delete(fake, run, billing, tmp_path, monkeypatch):
    pid, cid = billing
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("collection", "delete", "nova-dev-01", "orders", "billing", "invoices", input="invoices\n")
    assert r.exit_code == 0, r.output
    assert "  - collection nova-dev-01/orders/billing/invoices" in r.output
    assert "billing.invoices and all its documents are deleted." in r.output
    assert "deleted collection nova-dev-01/orders/billing/invoices" in r.output
    assert _deletes(fake, pid, cid) == ["/scopes/billing/collections/invoices"]
    scopes = file_clusters(tmp_path / "capella.yaml")[0]["buckets"][0]["scopes"]
    assert scopes == [{"name": "billing", "collections": [{"name": "refunds"}]}]


@pytest.mark.story("CAP-026", "AC1")
def test_collection_delete_ac1_wrong_name_cancels(fake, run, billing, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("collection", "delete", "nova-dev-01", "orders", "billing", "invoices", input="refunds\n")
    assert r.exit_code == 0 and "Cancelled; nothing was deleted." in r.output
    assert fake.writes() == []
    monkeypatch.setattr(console, "is_interactive", lambda: False)
    r = run("collection", "delete", "nova-dev-01", "orders", "billing", "invoices")
    assert r.exit_code == 1 and "--auto-approve" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-026", "AC2")
def test_scope_delete_ac2_lists_collections(fake, run, billing, tmp_path, monkeypatch):
    pid, cid = billing
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("scope", "delete", "nova-dev-01", "orders", "billing", input="billing\n")
    assert r.exit_code == 0, r.output
    assert "  - scope nova-dev-01/orders/billing" in r.output
    assert "billing · 2 collections: invoices, refunds" in r.output
    assert "These collections and all their documents are deleted." in r.output
    assert _deletes(fake, pid, cid) == ["/scopes/billing"]  # one DELETE for the scope and its collections
    assert "scopes" not in file_clusters(tmp_path / "capella.yaml")[0]["buckets"][0]
    assert "billing" not in fake.scopes[(cid, "b3JkZXJz")]


@pytest.mark.story("CAP-026", "AC2")
def test_scope_delete_ac2_protection_blocks(fake, run, billing):
    _, cid = billing
    fake.clusters[cid]["body"]["deletionProtection"] = True
    for args in (("scope", "delete", "nova-dev-01", "orders", "billing"),
                 ("collection", "delete", "nova-dev-01", "orders", "billing", "invoices")):
        r = run("--auto-approve", *args)
        assert r.exit_code == 4 and "deletion protection is on for nova-dev-01" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-026", "AC3")
@pytest.mark.parametrize("args", [("scope", "delete", "nova-dev-01", "orders", "_default"),
                                  ("scope", "delete", "nova-dev-01", "orders", "_system"),
                                  ("collection", "delete", "nova-dev-01", "orders", "_default", "_default")])
def test_scope_delete_ac3_system_refused(fake, run, billing, args):
    r = run("--auto-approve", *args)
    assert r.exit_code == 4
    assert "system scopes and collections cannot be deleted" in r.output
    assert fake.calls() == []  # refused before any API call


@pytest.mark.story("CAP-026", "AC4")
def test_collection_delete_ac4_prune_only(fake, run, billing, write_config, monkeypatch):
    pid, cid = billing
    write_config(MINIMAL + BILLING.replace("              - name: refunds\n", ""))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert fake.writes() == []
    assert "collection nova-dev-01/orders/billing/refunds" in run("plan").output.split("Unmanaged", 1)[1]
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("apply", "--prune", input="refunds\ny\n")
    assert r.exit_code == 0, r.output
    assert "  - collection nova-dev-01/orders/billing/refunds" in r.output
    assert "billing.refunds and all its documents are deleted." in r.output
    assert _deletes(fake, pid, cid) == ["/scopes/billing/collections/refunds"]


@pytest.mark.story("CAP-026", "AC4")
def test_scope_delete_ac4_prune_scope(fake, run, billing, write_config, monkeypatch):
    pid, cid = billing
    write_config(MINIMAL + "    buckets:\n      - name: orders\n        memoryAllocationInMb: 100\n")
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("apply", "--prune", input="wrong\n")
    assert r.exit_code == 0 and "Apply cancelled; nothing was changed." in r.output
    assert fake.writes() == []
    r = run("apply", "--prune", input="billing\ny\n")
    assert r.exit_code == 0, r.output
    assert "billing · 2 collections: invoices, refunds" in r.output
    assert _deletes(fake, pid, cid) == ["/scopes/billing"]


@pytest.mark.story("CAP-026", "AC4")
def test_collection_delete_ac4_prune_respects_protection(fake, run, billing, write_config):
    _, cid = billing
    fake.clusters[cid]["body"]["deletionProtection"] = True
    write_config(MINIMAL + BILLING.replace("              - name: refunds\n", ""))
    r = run("--auto-approve", "apply", "--prune")
    assert r.exit_code == 4
    assert "! collection nova-dev-01/orders/billing/refunds  deletion protection is on for nova-dev-01" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-026", "AC5")
def test_scope_delete_ac5_lists_dependent_credentials(fake, run, billing, monkeypatch):
    _, cid = billing
    seed_user(fake, cid, "billing_app", _grant("billing", ["invoices"]))
    seed_user(fake, cid, "billing_ro", _grant("billing"))
    seed_user(fake, cid, "refunds_app", _grant("billing", ["refunds"]))
    seed_user(fake, cid, "inventory_app", _grant("inventory"))
    monkeypatch.setattr(console, "is_interactive", lambda: True)

    r = run("collection", "delete", "nova-dev-01", "orders", "billing", "invoices", input="no\n")
    lines = r.output.splitlines()
    i = lines.index("  These credentials lose access to this collection:")
    assert lines[i + 1:i + 2] == ["    billing_app"] and "refunds_app" not in r.output

    r = run("scope", "delete", "nova-dev-01", "orders", "billing", input="no\n")
    lines = r.output.splitlines()
    i = lines.index("  These credentials lose access to this scope:")
    assert lines[i + 1:i + 4] == ["    billing_app", "    billing_ro", "    refunds_app"]
    assert "inventory_app" not in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-026", "AC5")
def test_collection_delete_ac5_prune_lists_dependent_credentials(fake, run, billing, write_config, monkeypatch):
    _, cid = billing
    seed_user(fake, cid, "refunds_app", _grant("billing", ["refunds"]))
    write_config(MINIMAL + BILLING.replace("              - name: refunds\n", ""))
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("apply", "--prune", input="refunds\ny\n")
    assert r.exit_code == 0, r.output
    assert "These credentials lose access to this collection:" in r.output and "refunds_app" in r.output


@pytest.mark.story("CAP-026", "AC6")
def test_collection_delete_ac6_rerun_noop(fake, run, billing):
    assert run("--auto-approve", "collection", "delete", "nova-dev-01", "orders", "billing", "invoices").exit_code == 0
    assert run("--auto-approve", "scope", "delete", "nova-dev-01", "orders", "billing").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "collection", "delete", "nova-dev-01", "orders", "billing", "invoices")
    assert r.exit_code == 0 and "collection nova-dev-01/orders/billing/invoices not found, nothing to do" in r.output
    r = run("--auto-approve", "scope", "delete", "nova-dev-01", "orders", "billing")
    assert r.exit_code == 0 and "scope nova-dev-01/orders/billing not found, nothing to do" in r.output
    assert fake.writes() == []
