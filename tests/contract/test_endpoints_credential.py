"""CAP-027 AC1, CAP-029 AC1: database credential endpoints against the v4.0 OpenAPI shapes."""
from __future__ import annotations

import pytest
import responses

from capellactl.api import endpoints as ep
from tests.contract.conftest import BASE

U = "/v4/organizations/org-1/projects/p-1/clusters/c-1/users"
ACCESS = [{"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders"}]}}]


@pytest.mark.story("CAP-027", "AC1")
def test_endpoints_ac1_credential_contract(rsps, client):
    body = {"name": "orders_app", "credentialType": "basic", "access": ACCESS, "password": "S3cret!Orders-pw"}
    rsps.add(responses.POST, BASE + U, status=201, json={"id": "u-1", "password": "S3cret!Orders-pw"},
             match=[responses.matchers.json_params_matcher(body)])
    rsps.add(responses.GET, BASE + U, json={"data": [{"id": "u-1", "name": "orders_app", "access": ACCESS}],
                                            "cursor": {"pages": {"page": 1, "last": 1, "perPage": 10}}})
    rsps.add(responses.GET, BASE + U + "/u-1", json={"id": "u-1", "name": "orders_app", "access": ACCESS},
             headers={"ETag": "3"})
    rsps.add(responses.PUT, BASE + U + "/u-1", status=204,
             match=[responses.matchers.json_params_matcher({"access": ACCESS}),
                    responses.matchers.header_matcher({"If-Match": "3"})])
    assert ep.create_credential(client, "p-1", "c-1", body) == ("u-1", "S3cret!Orders-pw")
    assert [u["name"] for u in ep.list_credentials(client, "p-1", "c-1")] == ["orders_app"]
    got, etag = ep.get_credential(client, "p-1", "c-1", "u-1")
    assert "password" not in got and etag == "3"
    ep.update_credential(client, "p-1", "c-1", "u-1", {"access": ACCESS}, if_match=etag)
    assert [c.request.method for c in rsps.calls] == ["POST", "GET", "GET", "PUT"]


@pytest.mark.story("CAP-029", "AC1")
def test_endpoints_ac1_delete_credential_contract(rsps, client):
    rsps.add(responses.DELETE, BASE + U + "/u-1", status=204)
    ep.delete_credential(client, "p-1", "c-1", "u-1")
    assert [(c.request.method, c.request.url) for c in rsps.calls] == [("DELETE", BASE + U + "/u-1")]
