"""CAP-003 AC3, AC4: retries, Retry-After, POST safety."""
from __future__ import annotations

import logging

import pytest
import requests
import responses

from capellactl.api.errors import AmbiguousWriteError, ServerError
from tests.contract.conftest import BASE

PATH = "/v4/organizations/org-1/projects"


@pytest.mark.story("CAP-003", "AC3")
def test_client_ac3_retry_after_honoured(rsps, client, fclock):
    rsps.add(responses.GET, BASE + PATH, status=429, headers={"Retry-After": "2"}, json={"message": "slow down"})
    rsps.add(responses.GET, BASE + PATH, json={"data": []})
    assert client.get(PATH).status == 200
    assert fclock.sleeps == [2.0]


@pytest.mark.story("CAP-003", "AC3")
def test_client_ac3_gives_up_after_six(rsps, client, fclock):
    for _ in range(6):
        rsps.add(responses.GET, BASE + PATH, status=503, json={"message": "unavailable"})
    with pytest.raises(ServerError):
        client.get(PATH)
    assert len(rsps.calls) == 6
    assert len(fclock.sleeps) == 5
    assert all(0 <= s <= 30 for s in fclock.sleeps)


@pytest.mark.story("CAP-003", "AC3")
def test_client_ac3_retry_logged(rsps, client, caplog):
    rsps.add(responses.GET, BASE + PATH, status=429, json={"message": "x"})
    rsps.add(responses.GET, BASE + PATH, json={"data": []})
    with caplog.at_level(logging.WARNING, logger="capellactl"):
        client.get(PATH)
    assert f"retrying GET {PATH} (attempt 2/6) after 429" in caplog.text


@pytest.mark.story("CAP-003", "AC4")
def test_client_ac4_post_read_timeout_not_retried(rsps, client):
    rsps.add(responses.POST, BASE + PATH, body=requests.exceptions.ReadTimeout("read timed out"))
    with pytest.raises(AmbiguousWriteError):
        client.post(PATH, {"name": "x"})
    assert len(rsps.calls) == 1


@pytest.mark.story("CAP-003", "AC4")
def test_client_ac4_post_429_retried(rsps, client):
    rsps.add(responses.POST, BASE + PATH, status=429, json={"message": "x"})
    rsps.add(responses.POST, BASE + PATH, status=201, json={"id": "p-1"})
    assert client.post(PATH, {"name": "x"}).body == {"id": "p-1"}
    assert len(rsps.calls) == 2


@pytest.mark.story("CAP-003", "AC4")
def test_client_ac4_post_connect_timeout_retried(rsps, client):
    rsps.add(responses.POST, BASE + PATH, body=requests.exceptions.ConnectTimeout("connect timed out"))
    rsps.add(responses.POST, BASE + PATH, status=201, json={"id": "p-1"})
    assert client.post(PATH, {"name": "x"}).body == {"id": "p-1"}


@pytest.mark.story("CAP-003", "AC4")
def test_client_ac4_post_5xx_not_retried(rsps, client):
    rsps.add(responses.POST, BASE + PATH, status=503, json={"message": "x"})
    with pytest.raises(ServerError):
        client.post(PATH, {"name": "x"})
    assert len(rsps.calls) == 1
