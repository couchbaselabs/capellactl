"""CAP-003 AC7: ETag round trip on cluster endpoints."""
from __future__ import annotations

import pytest
import responses

from capellactl.api import endpoints as ep
from capellactl.api.errors import PreconditionFailed
from tests.contract.conftest import BASE

C = "/v4/organizations/org-1/projects/p-1/clusters/c-1"


@pytest.mark.story("CAP-003", "AC7")
def test_endpoints_ac7_get_returns_etag(rsps, client):
    rsps.add(responses.GET, BASE + C, json={"id": "c-1"}, headers={"ETag": '"17"'})
    assert ep.get_cluster(client, "p-1", "c-1") == ({"id": "c-1"}, "17")


@pytest.mark.story("CAP-003", "AC7")
def test_endpoints_ac7_capella_version_etag_is_sent_bare(rsps, client):
    """Capella sends 'ETag: Version: 17'; If-Match must carry only '17' (spec example '12'), or every PUT gets 412."""
    rsps.add(responses.GET, BASE + C, json={"id": "c-1"}, headers={"ETag": "Version: 17"})
    rsps.add(responses.PUT, BASE + C, status=204)
    _, etag = ep.get_cluster(client, "p-1", "c-1")
    assert etag == "17"
    ep.update_cluster(client, "p-1", "c-1", {"name": "x"}, if_match=etag)
    assert rsps.calls[1].request.headers["If-Match"] == "17"


@pytest.mark.story("CAP-003", "AC7")
def test_endpoints_ac7_update_sends_if_match(rsps, client):
    rsps.add(responses.PUT, BASE + C, status=204)
    ep.update_cluster(client, "p-1", "c-1", {"name": "x"}, if_match="17")
    assert rsps.calls[0].request.headers["If-Match"] == "17"


@pytest.mark.story("CAP-003", "AC7")
def test_endpoints_ac7_412_raises(rsps, client):
    rsps.add(responses.PUT, BASE + C, status=412, json={"httpStatusCode": 412, "code": 4120, "message": "etag",
                                                         "hint": "re-read"})
    with pytest.raises(PreconditionFailed):
        ep.update_cluster(client, "p-1", "c-1", {"name": "x"}, if_match="16")


@pytest.mark.story("CAP-013", "AC1")
def test_endpoints_ac1_deletion_protection_contract(rsps, client):
    rsps.add(responses.PUT, BASE + C + "/deletionProtection", status=204,
             match=[responses.matchers.json_params_matcher({"deletionProtection": True})])
    ep.set_deletion_protection(client, "p-1", "c-1", True)
    assert len(rsps.calls) == 1


@pytest.mark.story("CAP-014", "AC1")
@pytest.mark.parametrize(("retain", "param"), [(True, "true"), (False, "false")])
def test_endpoints_ac1_delete_cluster_query_param(rsps, client, retain, param):
    rsps.add(responses.DELETE, BASE + C, status=202,
             match=[responses.matchers.query_param_matcher({"retainsnapshotbackups": param})])
    ep.delete_cluster(client, "p-1", "c-1", retain_snapshot_backups=retain)
    assert len(rsps.calls) == 1


@pytest.mark.story("CAP-019", "AC1")
def test_endpoints_ac1_activation_state_contract(rsps, client):
    a = BASE + "/v4/organizations/org-1/projects/p-1/clusters/c-1/activationState"
    rsps.add(responses.POST, a, status=202, match=[responses.matchers.json_params_matcher(
        {"turnOnLinkedAppService": True})])
    rsps.add(responses.DELETE, a, status=202)
    ep.turn_cluster_on(client, "p-1", "c-1", with_app_service=True)
    ep.turn_cluster_off(client, "p-1", "c-1")
    assert [c.request.method for c in rsps.calls] == ["POST", "DELETE"]
