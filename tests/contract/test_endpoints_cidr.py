"""CAP-022 AC1: allowed-CIDR endpoints against the v4.0 OpenAPI shapes."""
from __future__ import annotations

import pytest
import responses

from capellactl.api import endpoints as ep
from tests.contract.conftest import BASE

C = "/v4/organizations/org-1/projects/p-1/clusters/c-1/allowedcidrs"


@pytest.mark.story("CAP-022", "AC1")
def test_endpoints_ac1_allowed_cidr_contract(rsps, client):
    body = {"cidr": "198.51.100.0/24", "comment": "CI runners", "expiresAt": "2026-12-31T23:59:59Z"}
    rsps.add(responses.POST, BASE + C, status=201, json={"id": "cidr-1"},
             match=[responses.matchers.json_params_matcher(body)])
    rsps.add(responses.GET, BASE + C, json={"data": [{"id": "cidr-1", **body, "status": "active"}],
                                            "cursor": {"pages": {"page": 1, "last": 1, "perPage": 10}}})
    rsps.add(responses.DELETE, BASE + C + "/cidr-1", status=204)
    assert ep.create_allowed_cidr(client, "p-1", "c-1", body) == "cidr-1"
    assert [c["cidr"] for c in ep.list_allowed_cidrs(client, "p-1", "c-1")] == ["198.51.100.0/24"]
    ep.delete_allowed_cidr(client, "p-1", "c-1", "cidr-1")
    assert [c.request.method for c in rsps.calls] == ["POST", "GET", "DELETE"]
