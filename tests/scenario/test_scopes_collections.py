"""CAP-025: ensure scopes & collections, through apply and the scope/collection commands."""
from __future__ import annotations

import pytest

from tests.conftest import MINIMAL, file_clusters, seed_healthy
from tests.scenario.helpers import ORDERS_APP, ORDERS_BUCKET, ORDERS_PW, header

PW_ENV = {"ORDERS_APP_PASSWORD": ORDERS_PW}
ORDERS = """\
    buckets:
      - name: orders
        memoryAllocationInMb: 100
        scopes:
          - name: inventory
            collections:
              - name: items
              - name: suppliers
                maxTTL: -1
          - name: billing
            collections:
              - name: invoices
"""
SUPPLIERS = """\
    buckets:
      - name: orders
        memoryAllocationInMb: 100
        scopes:
          - name: inventory
            collections:
              - name: suppliers
                maxTTL: -1
"""
LEGACY = """\
    buckets:
      - name: orders
        memoryAllocationInMb: 100
        scopes:
          - name: _default
            collections:
              - name: legacy
"""
B = "/v4/organizations/org-1/projects/{pid}/clusters/{cid}/buckets/b3JkZXJz"


def _orders(fake, version="8.0.1"):
    pid, cid = seed_healthy(fake, couchbaseServer={"version": version})
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=100)
    return pid, cid


def _writes(fake, pid, cid):
    base = B.format(pid=pid, cid=cid)
    return [(c.method, c.path.replace(base, ""), c.body) for c in fake.writes()]


@pytest.mark.story("CAP-025", "AC1")
def test_scopes_ac1_create_order_and_bodies(fake, run, write_config):
    pid, cid = _orders(fake)
    write_config(MINIMAL + ORDERS)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    for line in ("  + scope nova-dev-01/orders/inventory", "  + collection nova-dev-01/orders/inventory/items",
                 "  + collection nova-dev-01/orders/inventory/suppliers  maxTTL -1",
                 "  + scope nova-dev-01/orders/billing", "  + collection nova-dev-01/orders/billing/invoices"):
        assert line in r.output
    assert _writes(fake, pid, cid) == [
        ("POST", "/scopes", {"name": "inventory"}),  # every scope, then every collection (CAP-030 AC1)
        ("POST", "/scopes", {"name": "billing"}),
        ("POST", "/scopes/inventory/collections", {"name": "items"}),  # maxTTL omitted when not set
        ("POST", "/scopes/inventory/collections", {"name": "suppliers", "maxTTL": -1}),
        ("POST", "/scopes/billing/collections", {"name": "invoices"}),
    ]


@pytest.mark.story("CAP-025", "AC1")
def test_scopes_ac1_new_bucket_children_after_bucket(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL + ORDERS)
    r = run("plan")
    assert "  + scope nova-dev-01/orders/inventory  (after bucket is created)" in r.output
    assert "  + collection nova-dev-01/orders/inventory/items  (after scope is created)" in r.output
    assert run("--auto-approve", "apply").exit_code == 0
    kinds = [c.path.rsplit("/", 1)[-1] for c in fake.writes()]
    assert kinds == ["buckets", "scopes", "scopes", "collections", "collections", "collections"]
    assert set(fake.scopes[(cid, "b3JkZXJz")]) == {"_default", "_system", "inventory", "billing"}


@pytest.mark.story("CAP-025", "AC2")
def test_collections_ac2_maxttl_update(fake, run, write_config):
    pid, cid = _orders(fake, "7.6.2")
    fake.seed_scope(cid, "orders", "inventory", {"suppliers": 0})
    write_config(MINIMAL + SUPPLIERS)
    r = run("plan")
    assert "  ~ collection nova-dev-01/orders/inventory/suppliers" in r.output
    assert "      maxTTL:  0 → -1" in r.output
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    puts = fake.calls("PUT")
    assert [(c.path.replace(B.format(pid=pid, cid=cid), ""), c.body) for c in puts] == [
        ("/scopes/inventory/collections/suppliers", {"maxTTL": -1})]
    assert header(puts[0], "If-Match") == "1"
    assert fake.scopes[(cid, "b3JkZXJz")]["inventory"]["suppliers"]["maxTTL"] == -1


@pytest.mark.story("CAP-025", "AC2")
def test_collections_ac2_stale_etag_replans(fake, run, write_config):
    _, cid = _orders(fake, "7.6.2")
    fake.seed_scope(cid, "orders", "inventory", {"suppliers": 0})
    write_config(MINIMAL + SUPPLIERS)
    fake.fail_next("PUT", "*/collections/suppliers", status=412)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert len(fake.calls("PUT")) == 2  # re-observed and retried once
    assert fake.scopes[(cid, "b3JkZXJz")]["inventory"]["suppliers"]["maxTTL"] == -1


@pytest.mark.story("CAP-025", "AC3")
def test_collections_ac3_old_server_blocked(fake, run, write_config):
    _, cid = _orders(fake, "7.2.4")
    fake.seed_scope(cid, "orders", "inventory", {"suppliers": 0})
    write_config(MINIMAL + SUPPLIERS)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4
    assert ("! collection nova-dev-01/orders/inventory/suppliers  maxTTL can only be changed on Couchbase Server "
            "7.6.0 or later (nova-dev-01 runs 7.2.4)") in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-025", "AC3")
def test_collections_ac3_old_server_still_creates(fake, run, write_config):
    _, cid = _orders(fake, "7.2.4")
    write_config(MINIMAL + SUPPLIERS)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output  # only changing maxTTL needs 7.6.0; creating with it does not
    assert fake.scopes[(cid, "b3JkZXJz")]["inventory"]["suppliers"]["maxTTL"] == -1


@pytest.mark.story("CAP-025", "AC5")
def test_scopes_ac5_default_scope_collections_only(fake, run, write_config):
    pid, cid = _orders(fake)
    write_config(MINIMAL + LEGACY)
    r = run("plan")
    assert "  + collection nova-dev-01/orders/_default/legacy" in r.output
    assert "+ scope" not in r.output
    assert "Plan: 1 to add, 0 to change, 0 to delete, 0 blocked." in r.output
    assert run("--auto-approve", "apply").exit_code == 0
    assert _writes(fake, pid, cid) == [("POST", "/scopes/_default/collections", {"name": "legacy"})]


@pytest.mark.story("CAP-025", "AC5")
def test_scopes_ac5_default_scope_on_new_bucket(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL + LEGACY)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert [c.path.rsplit("/", 1)[-1] for c in fake.writes()] == ["buckets", "collections"]
    assert "legacy" in fake.scopes[(cid, "b3JkZXJz")]["_default"]


@pytest.mark.story("CAP-025", "AC5")
def test_scopes_ac5_system_scope_ignored(fake, run, write_config):
    pid, cid = _orders(fake)
    fake.seed_scope(cid, "orders", "inventory", {"items": 0, "suppliers": -1})
    fake.seed_scope(cid, "orders", "legacy")
    write_config(MINIMAL + SUPPLIERS)
    r = run("plan")
    assert r.exit_code == 0, r.output
    unmanaged = r.output.split("Unmanaged", 1)[1]
    assert "scope nova-dev-01/orders/legacy" in unmanaged
    assert "collection nova-dev-01/orders/inventory/items" in unmanaged
    assert "_system" not in r.output and "_default" not in r.output
    r = run("--auto-approve", "apply", "--prune")
    assert r.exit_code == 0, r.output
    assert sorted((m, p) for m, p, _ in _writes(fake, pid, cid)) == [
        ("DELETE", "/scopes/inventory/collections/items"), ("DELETE", "/scopes/legacy")]
    assert {"_default", "_system"} <= set(fake.scopes[(cid, "b3JkZXJz")])


@pytest.mark.story("CAP-025", "AC7")
def test_scopes_ac7_before_credentials(fake, run, write_config):
    _, cid = _orders(fake)
    write_config(MINIMAL + ORDERS_BUCKET + ORDERS_APP)
    r = run("--auto-approve", "apply", extra_env=PW_ENV)
    assert r.exit_code == 0, r.output
    kinds = [c.path.rsplit("/", 1)[-1] for c in fake.writes()]
    assert kinds == ["scopes", "collections", "collections", "users"]


@pytest.mark.story("CAP-025", "AC8")
def test_scopes_ac8_rerun_zero_writes(fake, run, write_config):
    _orders(fake)
    write_config(MINIMAL + ORDERS)
    assert run("--auto-approve", "apply").exit_code == 0
    fake.reset_calls()
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0, r.output
    assert "Plan: 0 to add, 0 to change, 0 to delete, 0 blocked." in r.output
    assert "Unmanaged" not in r.output
    assert run("--auto-approve", "apply").exit_code == 0
    assert fake.writes() == []


# ------------------------------------------------------------------ commands
@pytest.mark.story("CAP-025", "AC1")
def test_scope_cli_ac1_create_records_and_applies(fake, run, write_config, tmp_path):
    pid, cid = _orders(fake)
    write_config(MINIMAL + "    buckets:\n      - name: orders\n        memoryAllocationInMb: 100\n")
    r = run("--auto-approve", "scope", "create", "nova-dev-01", "orders", "billing")
    assert r.exit_code == 0, r.output
    assert "  + scope nova-dev-01/orders/billing" in r.output
    assert file_clusters(tmp_path / "capella.yaml")[0]["buckets"][0]["scopes"] == [{"name": "billing"}]
    assert _writes(fake, pid, cid) == [("POST", "/scopes", {"name": "billing"})]
    fake.reset_calls()
    r = run("--auto-approve", "scope", "create", "nova-dev-01", "orders", "billing")
    assert r.exit_code == 0 and "scope nova-dev-01/orders/billing already exists in Capella" in r.output
    assert fake.writes() == []
    lines = run("scope", "list", "nova-dev-01", "orders").output.splitlines()
    assert lines[0].split() == ["S.NO", "NAME", "COLLECTIONS", "IN", "FILE"]
    assert ["billing", "0", "yes"] in [ln.split()[1:] for ln in lines]
    assert ["_system", "0", "system"] in [ln.split()[1:] for ln in lines]


@pytest.mark.story("CAP-025", "AC1")
def test_scope_cli_ac1_bucket_not_in_file(fake, run, write_config):
    _orders(fake)
    write_config()
    r = run("--auto-approve", "scope", "create", "nova-dev-01", "orders", "billing")
    assert r.exit_code == 3 and "bucket create nova-dev-01 orders" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-025", "AC5")
def test_scope_cli_ac5_system_scope_not_created(fake, run, write_config):
    _orders(fake)
    write_config(MINIMAL + "    buckets:\n      - name: orders\n        memoryAllocationInMb: 100\n")
    r = run("--auto-approve", "scope", "create", "nova-dev-01", "orders", "_default")
    assert r.exit_code == 3 and "collection create nova-dev-01 orders _default NAME" in r.output
    r = run("--auto-approve", "collection", "create", "nova-dev-01", "orders", "_default", "_default")
    assert r.exit_code == 3 and "system collection" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-025", "AC1")
def test_collection_cli_ac1_create_adds_scope(fake, run, write_config, tmp_path):
    pid, cid = _orders(fake)
    write_config(MINIMAL + "    buckets:\n      - name: orders\n        memoryAllocationInMb: 100\n")
    r = run("--auto-approve", "collection", "create", "nova-dev-01", "orders", "inventory", "items",
            "--max-ttl", "3600")
    assert r.exit_code == 0, r.output
    assert file_clusters(tmp_path / "capella.yaml")[0]["buckets"][0]["scopes"] == [
        {"name": "inventory", "collections": [{"name": "items", "maxTTL": 3600}]}]
    assert _writes(fake, pid, cid) == [("POST", "/scopes", {"name": "inventory"}),
                                       ("POST", "/scopes/inventory/collections", {"name": "items", "maxTTL": 3600})]
    r = run("--auto-approve", "collection", "create", "nova-dev-01", "orders", "inventory", "items")
    assert r.exit_code == 4 and "collection update nova-dev-01 orders inventory items" in r.output
    lines = [ln.split()[1:] for ln in run("collection", "list", "nova-dev-01", "orders", "inventory").output.splitlines()]
    assert ["items", "3600", "yes"] in lines


@pytest.mark.story("CAP-025", "AC2")
def test_collection_cli_ac2_update_max_ttl(fake, run, write_config, tmp_path):
    pid, cid = _orders(fake, "7.6.2")
    fake.seed_scope(cid, "orders", "inventory", {"suppliers": 0})
    write_config(MINIMAL + SUPPLIERS.replace("                maxTTL: -1\n", ""))
    r = run("--auto-approve", "collection", "update", "nova-dev-01", "orders", "inventory", "suppliers",
            "--max-ttl", "-1")
    assert r.exit_code == 0, r.output
    assert "      maxTTL:  0 → -1" in r.output
    put = fake.calls("PUT")
    assert [c.body for c in put] == [{"maxTTL": -1}] and header(put[0], "If-Match") == "1"
    coll = file_clusters(tmp_path / "capella.yaml")[0]["buckets"][0]["scopes"][0]["collections"][0]
    assert coll == {"name": "suppliers", "maxTTL": -1}
    r = run("--auto-approve", "collection", "update", "nova-dev-01", "orders", "inventory", "nope", "--max-ttl", "1")
    assert r.exit_code == 3 and "collection create nova-dev-01 orders inventory nope" in r.output
