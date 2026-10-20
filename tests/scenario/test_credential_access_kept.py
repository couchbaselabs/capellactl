"""A credential never loses its access: rotation sends it, and access removed in Capella is restored (2026-10-07)."""
from __future__ import annotations

import pytest
import yaml

from tests.conftest import seed_healthy

PW = {"AIRLINE_PW": "Demo-A1rline-2026!"}


@pytest.fixture
def airline(fake, run, tmp_path):
    _, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "demo", memoryAllocationInMb=512)
    assert run("import").exit_code == 0
    assert run("--auto-approve", "collection", "create", "nova-dev-01", "demo", "inventory", "airline").exit_code == 0
    r = run("--auto-approve", "credential", "create", "nova-dev-01", "airline_app", "--privileges", "read+write",
            "--bucket", "demo", "--scope", "inventory", "--collection", "airline", "--password-env", "AIRLINE_PW",
            extra_env=PW)
    assert r.exit_code == 0, r.output
    return next(u for u in fake.users.values() if u["name"] == "airline_app"), tmp_path / "capella.yaml"


@pytest.mark.story("CAP-028", "AC1")
def test_rotation_ac1_keeps_access(fake, run, airline):
    user, _ = airline
    before = user["access"]
    r = run("--auto-approve", "credential", "update", "nova-dev-01", "airline_app", "--rotate-password",
            extra_env={"AIRLINE_PW": "Demo-A1rline-2026-v2!"})
    assert r.exit_code == 0 and "password rotated for airline_app" in r.output, r.output
    assert user["access"] == before and user["_password"] == "Demo-A1rline-2026-v2!"
    assert "No changes" in run("--auto-approve", "apply", extra_env=PW).output


@pytest.mark.story("CAP-027", "AC4")
def test_credential_ac4_access_removed_in_capella_is_restored(fake, run, airline):
    user, _ = airline
    user["access"] = []  # e.g. removed in the Capella UI
    r = run("plan", extra_env=PW)
    assert "advanced credential" not in r.output
    assert "~ credential nova-dev-01/airline_app" in r.output, r.output
    assert run("--auto-approve", "apply", extra_env=PW).exit_code == 0
    assert user["access"] and "No changes" in run("--auto-approve", "apply", extra_env=PW).output


@pytest.mark.story("CAP-038", "AC9")
def test_sync_ac9_keeps_access_capella_lost(fake, run, airline):
    user, cfg = airline
    user["access"] = []
    r = run("sync", extra_env=PW)
    assert r.exit_code == 0, r.output
    assert "credential nova-dev-01/airline_app has no access in Capella; kept its access" in r.output
    cred = next(u for u in yaml.safe_load(cfg.read_text(encoding="utf-8"))["projects"][0]["clusters"][0]["databaseCredentials"]
                if u["name"] == "airline_app")
    assert cred["password"] == "${AIRLINE_PW}" and cred["access"][0]["resources"]["buckets"][0]["name"] == "demo"
    assert run("validate", extra_env=PW).exit_code == 0


@pytest.mark.story("CAP-036", "AC1")
def test_import_ac1_credential_without_access_listed_as_comment(fake, run, airline):
    user, cfg = airline
    user["access"] = []
    assert run("import", "--force").exit_code == 0
    text = cfg.read_text(encoding="utf-8")
    assert "airline_app has no access in Capella, so it is listed here for reference" in text
    r = run("validate")
    assert r.exit_code == 0, r.output + text
