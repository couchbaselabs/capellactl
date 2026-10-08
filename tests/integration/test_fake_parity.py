"""CAP-004 AC6: compare the fake's response shapes with a real sandbox organization (nightly, CAP-032)."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-004", "AC6")
def test_fake_ac6_response_shape_parity(clock):
    if not (os.environ.get("CAPELLA_SANDBOX_API_KEY") and os.environ.get("CAPELLA_SANDBOX_ORG_ID")):
        pytest.skip("needs CAPELLA_SANDBOX_API_KEY and CAPELLA_SANDBOX_ORG_ID")
    import responses

    from capellactl.api import endpoints as ep
    from capellactl.api.client import CapellaClient
    from tests.fakes.capella import FakeCapella

    real = CapellaClient(os.environ["CAPELLA_SANDBOX_API_KEY"], os.environ["CAPELLA_SANDBOX_ORG_ID"])
    real_projects = ep.list_projects(real)
    with responses.RequestsMock() as rsps:
        fake = FakeCapella(org_id="org-1", clock=clock)
        fake.install(rsps)
        fake.seed_project("p")
        fake_projects = ep.list_projects(CapellaClient("k-123456", "org-1", clock=clock))
    if real_projects:
        missing = set(real_projects[0]) - set(fake_projects[0])
        assert not missing, f"fake project is missing fields: {sorted(missing)}"
