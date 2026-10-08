"""CAP-003 AC1, AC8: headers and redacted debug logging."""
from __future__ import annotations

import logging
import platform

import pytest
import responses

from capellactl import __version__
from tests.conftest import assert_no_secret
from tests.contract.conftest import BASE, KEY


@pytest.mark.story("CAP-003", "AC1")
def test_client_ac1_headers(rsps, client):
    rsps.add(responses.GET, f"{BASE}/v4/organizations/org-1", json={"id": "org-1"})
    client.get("/v4/organizations/org-1")
    h = rsps.calls[0].request.headers
    assert h["Authorization"] == f"Bearer {KEY}"
    assert h["Accept"] == "application/json"
    assert h["User-Agent"] == f"capellactl/{__version__} (python/{platform.python_version()})"


@pytest.mark.story("CAP-003", "AC8")
def test_client_ac8_debug_log_redacted(rsps, client, caplog):
    rsps.add(responses.POST, f"{BASE}/v4/organizations/org-1/projects/p/clusters/c/users",
             json={"id": "u-1", "password": "Gen3rated!Secret"}, status=201)
    with caplog.at_level(logging.DEBUG, logger="capellactl"):
        client.post("/v4/organizations/org-1/projects/p/clusters/c/users",
                    {"name": "app", "password": "Typed!Secret-99"})
    text = caplog.text
    assert "POST /v4/organizations/org-1/projects/p/clusters/c/users 201" in text
    assert "'password': '***'" in text
    assert_no_secret(text, "Typed!Secret-99", KEY)
