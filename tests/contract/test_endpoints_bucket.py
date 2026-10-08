"""CAP-023 AC1 / CAP-024: bucket endpoint functions send the right method, path and body."""
from __future__ import annotations

import json

import pytest
import responses

from capellactl.api import endpoints as ep
from tests.contract.conftest import BASE

C = "/v4/organizations/org-1/projects/p-1/clusters/c-1"


@pytest.mark.story("CAP-023", "AC1")
def test_endpoints_ac1_bucket_contract(rsps, client):
    rsps.add(responses.POST, BASE + C + "/buckets", status=201, json={"id": "b3JkZXJz"})
    rsps.add(responses.PUT, BASE + C + "/buckets/b3JkZXJz", status=204)
    rsps.add(responses.GET, BASE + C + "/stats", json={"totalMemoryInMb": 4096, "freeMemoryInMb": 2048,
                                                       "maxReplicas": 2})
    rsps.add(responses.DELETE, BASE + C + "/buckets/b3JkZXJz", status=204)
    body = {"name": "orders", "storageBackend": "magma", "memoryAllocationInMb": 1024, "flushEnabled": False}
    assert ep.create_bucket(client, "p-1", "c-1", body) == "b3JkZXJz"
    ep.update_bucket(client, "p-1", "c-1", "b3JkZXJz", {"memoryAllocationInMb": 2048, "durabilityLevel": "none",
                                                         "replicas": 1, "timeToLiveInSeconds": 0})
    assert ep.get_cluster_stats(client, "p-1", "c-1")["freeMemoryInMb"] == 2048
    ep.delete_bucket(client, "p-1", "c-1", "b3JkZXJz")
    sent = [(c.request.method, c.request.url.replace(BASE, "")) for c in rsps.calls]
    assert sent == [("POST", C + "/buckets"), ("PUT", C + "/buckets/b3JkZXJz"), ("GET", C + "/stats"),
                    ("DELETE", C + "/buckets/b3JkZXJz")]
    assert json.loads(rsps.calls[0].request.body) == body


@pytest.mark.story("CAP-023", "AC1")
def test_endpoints_ac1_free_tier_bucket_contract(rsps, client):
    F = C + "/buckets/freeTier"
    rsps.add(responses.GET, BASE + F, json={"data": [{"id": "b3JkZXJz", "name": "orders"}],
                                            "clusterStats": {"freeMemoryInMb": 640, "totalMemoryInMb": 1040,
                                                             "maxReplicas": 0}})
    rsps.add(responses.POST, BASE + F, status=201, json={"id": "b3JkZXJz"})
    rsps.add(responses.GET, BASE + F + "/b3JkZXJz", json={"id": "b3JkZXJz"})
    rsps.add(responses.PUT, BASE + F + "/b3JkZXJz", status=204)
    rsps.add(responses.DELETE, BASE + F + "/b3JkZXJz", status=204)
    buckets, stats = ep.list_free_buckets(client, "p-1", "c-1")
    assert buckets == [{"id": "b3JkZXJz", "name": "orders"}] and stats["freeMemoryInMb"] == 640
    assert ep.create_free_bucket(client, "p-1", "c-1", {"name": "orders", "memoryAllocationInMb": 100}) == "b3JkZXJz"
    assert ep.get_free_bucket(client, "p-1", "c-1", "b3JkZXJz")[0] == {"id": "b3JkZXJz"}
    ep.update_free_bucket(client, "p-1", "c-1", "b3JkZXJz", {"memoryAllocationInMb": 200})
    ep.delete_free_bucket(client, "p-1", "c-1", "b3JkZXJz")
    assert "page" not in rsps.calls[0].request.url  # the free-tier list is not paginated
    assert [c.request.method for c in rsps.calls] == ["GET", "POST", "GET", "PUT", "DELETE"]
