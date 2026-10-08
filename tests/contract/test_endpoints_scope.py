"""CAP-025 AC1 / CAP-026: scope and collection endpoint functions send the right method, path and body."""
from __future__ import annotations

import json

import pytest
import responses

from capellactl.api import endpoints as ep
from tests.contract.conftest import BASE

B = "/v4/organizations/org-1/projects/p-1/clusters/c-1/buckets/b3JkZXJz"


@pytest.mark.story("CAP-025", "AC1")
def test_endpoints_ac1_scope_collection_contract(rsps, client):
    rsps.add(responses.GET, BASE + B + "/scopes", json={"scopes": [{"name": "_default", "collections": []}]})
    rsps.add(responses.POST, BASE + B + "/scopes", status=201)
    rsps.add(responses.GET, BASE + B + "/scopes/inventory", json={"name": "inventory", "collections": []})
    rsps.add(responses.GET, BASE + B + "/scopes/inventory/collections", json={"data": [{"name": "items", "maxTTL": 0}]})
    rsps.add(responses.POST, BASE + B + "/scopes/inventory/collections", status=201)
    rsps.add(responses.GET, BASE + B + "/scopes/inventory/collections/items", json={"name": "items", "maxTTL": 0},
             headers={"ETag": "3"})
    rsps.add(responses.PUT, BASE + B + "/scopes/inventory/collections/items", status=204)
    rsps.add(responses.DELETE, BASE + B + "/scopes/inventory/collections/items", status=204)
    rsps.add(responses.DELETE, BASE + B + "/scopes/inventory", status=204)

    assert [s["name"] for s in ep.list_scopes(client, "p-1", "c-1", "b3JkZXJz")] == ["_default"]
    ep.create_scope(client, "p-1", "c-1", "b3JkZXJz", "inventory")
    assert ep.get_scope(client, "p-1", "c-1", "b3JkZXJz", "inventory")[0]["name"] == "inventory"
    assert ep.list_collections(client, "p-1", "c-1", "b3JkZXJz", "inventory") == [{"name": "items", "maxTTL": 0}]
    ep.create_collection(client, "p-1", "c-1", "b3JkZXJz", "inventory", {"name": "items", "maxTTL": -1})
    body, etag = ep.get_collection(client, "p-1", "c-1", "b3JkZXJz", "inventory", "items")
    ep.update_collection(client, "p-1", "c-1", "b3JkZXJz", "inventory", "items", -1, if_match=etag)
    ep.delete_collection(client, "p-1", "c-1", "b3JkZXJz", "inventory", "items")
    ep.delete_scope(client, "p-1", "c-1", "b3JkZXJz", "inventory")

    sent = [(c.request.method, c.request.url.replace(BASE + B, "").split("?")[0]) for c in rsps.calls]
    assert sent == [("GET", "/scopes"), ("POST", "/scopes"), ("GET", "/scopes/inventory"),
                    ("GET", "/scopes/inventory/collections"), ("POST", "/scopes/inventory/collections"),
                    ("GET", "/scopes/inventory/collections/items"), ("PUT", "/scopes/inventory/collections/items"),
                    ("DELETE", "/scopes/inventory/collections/items"), ("DELETE", "/scopes/inventory")]
    assert json.loads(rsps.calls[1].request.body) == {"name": "inventory"}
    assert json.loads(rsps.calls[4].request.body) == {"name": "items", "maxTTL": -1}
    assert json.loads(rsps.calls[6].request.body) == {"maxTTL": -1}
    assert etag == "3" and rsps.calls[6].request.headers["If-Match"] == "3"
