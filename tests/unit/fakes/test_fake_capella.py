"""CAP-004: the fake Capella harness behaves like the API."""
from __future__ import annotations

import contextlib

import pytest

from capellactl.api import endpoints as ep
from capellactl.api.client import CapellaClient
from capellactl.api.errors import CapellaApiError, Conflict, NotFound, PreconditionFailed
from tests.fakes.capella import FakeCapella


@pytest.fixture
def client(fake: FakeCapella, clock) -> CapellaClient:
    return CapellaClient("k-123456", "org-1", clock=clock)


@pytest.mark.story("CAP-004", "AC1")
def test_fake_ac1_handles_every_inventory_endpoint(fake, client):
    ids = {"{organizationId}": "org-1", "{projectId}": "p-x", "{clusterId}": "c-x", "{bucketId}": "Yg",
           "{allowedCidrId}": "cidr-x", "{scopeName}": "s", "{collectionName}": "n", "{userId}": "u-x"}
    for method, template in ep.INVENTORY:
        path = template
        for k, v in ids.items():
            path = path.replace(k, v)
        with contextlib.suppress(CapellaApiError):  # 404/422 etc. are fine: the route exists
            client.request(method, path, json={} if method in ("POST", "PUT") else None)


@pytest.mark.story("CAP-004", "AC1")
def test_fake_ac1_unhandled_call_fails_loudly(fake, client):
    with pytest.raises(AssertionError, match="FakeCapella: unhandled GET /v4/organizations/org-1/nope"):
        client.get("/v4/organizations/org-1/nope")


@pytest.mark.story("CAP-004", "AC2")
def test_fake_ac2_create_deploying_then_healthy(fake, client):
    pid = fake.seed_project("p")
    cid = ep.create_cluster(client, pid, {"name": "c", "cloudProvider": {"type": "aws", "region": "r"},
                                          "serviceGroups": [], "availability": {"type": "multi"},
                                          "support": {"plan": "basic"}})
    assert ep.get_cluster(client, pid, cid)[0]["currentState"] == "deploying"
    fake.advance(fake.step_seconds)
    assert ep.get_cluster(client, pid, cid)[0]["currentState"] == "healthy"


@pytest.mark.story("CAP-004", "AC2")
def test_fake_ac2_delete_then_404(fake, client):
    pid = fake.seed_project("p")
    cid = fake.seed_cluster(pid, "c")
    ep.delete_cluster(client, pid, cid)
    assert ep.get_cluster(client, pid, cid)[0]["currentState"] == "destroying"
    fake.advance(fake.step_seconds)
    with pytest.raises(NotFound):
        ep.get_cluster(client, pid, cid)


@pytest.mark.story("CAP-004", "AC2")
def test_fake_ac2_power_cycle_states(fake, client):
    pid = fake.seed_project("p")
    cid = fake.seed_cluster(pid, "c")
    ep.turn_cluster_off(client, pid, cid)
    assert ep.get_cluster(client, pid, cid)[0]["currentState"] == "turningOff"
    fake.advance(fake.step_seconds)
    assert ep.get_cluster(client, pid, cid)[0]["currentState"] == "turnedOff"
    ep.turn_cluster_on(client, pid, cid)
    fake.advance(fake.step_seconds)
    assert ep.get_cluster(client, pid, cid)[0]["currentState"] == "healthy"


@pytest.mark.story("CAP-004", "AC3")
def test_fake_ac3_stale_etag_412(fake, client):
    pid = fake.seed_project("p")
    _, etag = ep.get_project(client, pid)
    ep.update_project(client, pid, {"name": "p2"}, if_match=etag)
    with pytest.raises(PreconditionFailed):
        ep.update_project(client, pid, {"name": "p3"}, if_match=etag)


@pytest.mark.story("CAP-004", "AC3")
@pytest.mark.parametrize("kind", ["bucket", "scope", "collection", "credential", "cidr"])
def test_fake_ac3_duplicate_child_409(fake, client, kind):
    pid = fake.seed_project("p")
    cid = fake.seed_cluster(pid, "c")
    bid = fake.seed_bucket(cid, "b")
    create = {
        "bucket": lambda: ep.create_bucket(client, pid, cid, {"name": "b"}),
        "scope": lambda: ep.create_scope(client, pid, cid, bid, "s1"),
        "collection": lambda: ep.create_collection(client, pid, cid, bid, "_default", {"name": "c1"}),
        "credential": lambda: ep.create_credential(client, pid, cid, {"name": "u1", "access": []}),
        "cidr": lambda: ep.create_allowed_cidr(client, pid, cid, {"cidr": "10.0.0.0/24"}),
    }[kind]
    if kind != "bucket":
        create()
    with pytest.raises(Conflict) as ei:
        create()
    assert ei.value.code == 1010


@pytest.mark.story("CAP-004", "AC3")
def test_fake_ac3_duplicate_cluster_name_allowed(fake, client):
    pid = fake.seed_project("p")
    fake.seed_project("p")
    body = {"name": "c", "cloudProvider": {"type": "aws", "region": "r"}, "serviceGroups": [],
            "availability": {"type": "multi"}, "support": {"plan": "basic"}}
    a, b = ep.create_cluster(client, pid, body), ep.create_cluster(client, pid, body)
    assert a != b
    assert [p["name"] for p in ep.list_projects(client)] == ["p", "p"]


@pytest.mark.story("CAP-004", "AC4")
def test_fake_ac4_writes_excludes_gets(fake, client):
    pid = fake.seed_project("p")
    ep.list_projects(client)
    ep.update_project(client, pid, {"name": "x"})
    assert [(c.method, c.path) for c in fake.writes()] == [("PUT", f"/v4/organizations/org-1/projects/{pid}")]


@pytest.mark.story("CAP-004", "AC4")
def test_fake_ac4_call_repr_redacts_password(fake, client):
    pid = fake.seed_project("p")
    cid = fake.seed_cluster(pid, "c")
    ep.create_credential(client, pid, cid, {"name": "u", "password": "Very!Secret-1", "access": []})
    assert "Very!Secret-1" not in repr(fake.writes())


@pytest.mark.story("CAP-004", "AC5")
def test_fake_ac5_fail_next_times(fake, clock):
    c = CapellaClient("k-123456", "org-1", clock=clock, max_attempts=1)
    fake.fail_next("GET", "/v4/organizations/org-1/projects", 503, times=2)
    for _ in range(2):
        with pytest.raises(CapellaApiError):
            ep.list_projects(c)
    assert ep.list_projects(c) == []
