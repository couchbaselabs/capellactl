"""CAP-003 AC1, AC2: authentication behaviour of the CLI."""
from __future__ import annotations

import pytest

from tests.conftest import seed_healthy


@pytest.mark.story("CAP-003", "AC1")
def test_client_ac1_missing_key_exit_3_no_request(fake, run, write_config):
    write_config()
    r = run("plan", no_env=True, extra_env={"CAPELLA_ORG_ID": "org-1"})
    assert r.exit_code == 3
    assert "no API key: set CAPELLA_API_KEY or run 'capellactl configure'" in r.output
    assert fake.calls() == []


@pytest.mark.story("CAP-003", "AC2")
def test_client_ac2_401_message(fake, run, write_config):
    fake.api_keys = {"some-other-key"}
    write_config()
    r = run("plan")
    assert r.exit_code == 1
    assert "API Key Token rejected: check that CAPELLA_API_KEY" in r.output
    assert "Capella says: The request is unauthorized." in r.output and "allowlist" in r.output


@pytest.mark.story("CAP-003", "AC2")
def test_client_ac2_403_names_roles(fake, run, write_config):
    fake.seed_project("nova-dev", description="Nova development environment")
    fake.fail_next("POST", "*/clusters", 403)
    write_config()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 1
    assert "injected 403" in r.output
    assert "required role: Organization Owner, Project Owner or Project Manager" in r.output


@pytest.mark.story("CAP-003", "AC2")
def test_client_ac2_403_on_read_names_roles(fake, run, write_config):
    seed_healthy(fake)
    fake.fail_next("GET", "*/projects/*/clusters", 403)
    write_config()
    r = run("plan")
    assert r.exit_code == 1
    assert "required role: Organization Owner, Project Owner or Project Manager" in r.output
