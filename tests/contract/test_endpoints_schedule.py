"""CAP-020 AC3 / CAP-021 AC1: on/off schedule endpoints against the v4.0 OpenAPI shapes."""
from __future__ import annotations

import pytest
import responses

from capellactl.api import endpoints as ep
from capellactl.resources.schedule import expand
from tests.contract.conftest import BASE

S = "/v4/organizations/org-1/projects/p-1/clusters/c-1/onOffSchedule"
BODY = expand({"timezone": "US/Pacific", "weekdays": "08:00-18:00", "weekend": "off"})


@pytest.mark.story("CAP-020", "AC3")
def test_endpoints_ac3_schedule_contract(rsps, client):
    rsps.add(responses.POST, BASE + S, status=204, match=[responses.matchers.json_params_matcher(BODY)])
    rsps.add(responses.GET, BASE + S, json={"activationStatus": "active", **BODY}, headers={"ETag": "Version: 2"})
    rsps.add(responses.PUT, BASE + S, status=204, match=[responses.matchers.json_params_matcher(BODY)])
    rsps.add(responses.DELETE, BASE + S, status=204)
    ep.create_schedule(client, "p-1", "c-1", BODY)
    body, etag = ep.get_schedule(client, "p-1", "c-1")
    assert body["days"] == BODY["days"] and etag
    ep.update_schedule(client, "p-1", "c-1", BODY, if_match=etag)
    ep.delete_schedule(client, "p-1", "c-1")
    assert [c.request.method for c in rsps.calls] == ["POST", "GET", "PUT", "DELETE"]
    assert rsps.calls[2].request.headers.get("If-Match")


@pytest.mark.story("CAP-021", "AC1")
def test_endpoints_ac1_schedule_activation_contract(rsps, client):
    rsps.add(responses.DELETE, BASE + S + "/activationState", status=204)
    rsps.add(responses.POST, BASE + S + "/activationState", status=204)
    ep.pause_schedule(client, "p-1", "c-1")
    ep.resume_schedule(client, "p-1", "c-1")
    assert [c.request.method for c in rsps.calls] == ["DELETE", "POST"]
