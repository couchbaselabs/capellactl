"""CAP-027: canonical access comparison and plan summaries."""
from __future__ import annotations

import pytest

from capellactl.resources.credential import access_changes, access_map, access_summary, api_access


@pytest.mark.story("CAP-027", "AC3")
def test_credential_normalize_ac3_equivalent_access():
    capella = [{"privileges": ["read", "write"],
                "resources": {"buckets": [{"name": "orders", "scopes": [{"name": "inventory",
                                                                          "collections": ["suppliers", "items"]}]},
                                          {"name": "events"}]}}]
    file = [{"privileges": ["data_writer", "data_reader"],
             "resources": {"buckets": [{"name": "events"},
                                       {"name": "orders", "scopes": [{"name": "inventory",
                                                                      "collections": ["items", "suppliers"]}]}]}}]
    assert access_map(capella) == access_map(file)
    assert access_changes(file, capella) == []


@pytest.mark.story("CAP-027", "AC3")
def test_credential_normalize_ac3_grouping_does_not_matter():
    """Two grants on one bucket equal one grant with both privileges."""
    split = [{"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders"}]}},
             {"privileges": ["data_writer"], "resources": {"buckets": [{"name": "orders"}]}}]
    merged = [{"privileges": ["read", "write"], "resources": {"buckets": [{"name": "orders"}]}}]
    assert access_changes(split, merged) == []


@pytest.mark.story("CAP-027", "AC4")
def test_credential_ac4_changes_per_resource():
    before = [{"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders", "scopes": [{"name": "inv"}]}]}}]
    after = [{"privileges": ["data_reader", "data_writer"],
              "resources": {"buckets": [{"name": "orders", "scopes": [{"name": "inv"}]}]}},
             {"privileges": ["read"]}]
    assert [(c.path, c.before, c.after) for c in access_changes(after, before)] == [
        ("orders/inv", "read", "read+write"), ("(all buckets)", None, "read")]


@pytest.mark.story("CAP-027", "AC1")
def test_credential_ac1_summary_and_body():
    access = [{"privileges": ["read"]},
              {"privileges": ["data_reader", "data_writer"],
               "resources": {"buckets": [{"name": "orders", "external": True,
                                          "scopes": [{"name": "inventory", "collections": ["suppliers", "items"]}]}]}}]
    assert access_summary(access) == "read+write · orders/inventory/{items,suppliers}; read · (all buckets)"
    assert api_access(access)[1] == {"privileges": ["data_reader", "data_writer"],
                                     "resources": {"buckets": [{"name": "orders", "scopes": [
                                         {"name": "inventory", "collections": ["suppliers", "items"]}]}]}}
