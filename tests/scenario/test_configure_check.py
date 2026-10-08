"""CAP-047: configure and import check an existing capella.yaml against the key's organization."""
from __future__ import annotations

import pytest
import yaml

from tests.conftest import MINIMAL, seed_healthy

KEY = "profile-key-0987654321"
OTHER = MINIMAL.replace("${CAPELLA_ORG_ID}", "org-other")
TWO_PROJECTS = """\
apiVersion: capellactl/v1
organizationId: org-1
projects:
  - name: nova-dev
  - name: free-proj
"""


@pytest.fixture
def interactive(monkeypatch):
    from capellactl.cli import console as console_mod

    monkeypatch.setattr(console_mod, "is_interactive", lambda: True)


@pytest.mark.story("CAP-047", "AC1")
def test_configure_check_ac1_org_mismatch_reported(fake, run, write_config):
    seed_healthy(fake)
    p = write_config(OTHER)
    r = run("configure", input=f"{KEY}\n", no_env=True)
    assert r.exit_code == 0, r.output
    assert "profile 'default' saved" in r.output
    assert "capella.yaml is for organization org-other, but this key is for Nova Corp (org-1)" in r.output
    assert "capellactl import --force" in r.output and "capellactl configure --profile NAME" in r.output
    assert "Back up" not in r.output
    assert p.read_text() == OTHER
    assert fake.writes() == []


@pytest.mark.story("CAP-047", "AC2")
def test_configure_check_ac2_reimport_on_yes(fake, run, write_config, tmp_path, interactive):
    seed_healthy(fake)
    p = write_config(OTHER)
    r = run("configure", input=f"{KEY}\ny\n", no_env=True)
    assert r.exit_code == 0, r.output
    assert "Back up capella.yaml and re-import it for Nova Corp?" in r.output
    assert (tmp_path / "capella.yaml.bak").read_text() == OTHER
    data = yaml.safe_load(p.read_text())
    assert data["organizationId"] == "org-1"
    assert [x["name"] for x in data["projects"]] == ["nova-dev"]
    assert fake.writes() == []


@pytest.mark.story("CAP-047", "AC2")
def test_configure_check_ac2_default_keeps_file(fake, run, write_config, tmp_path, interactive):
    seed_healthy(fake)
    p = write_config(OTHER)
    for answer in ("n\n", "\n"):
        r = run("configure", input=f"{KEY}\n{answer}", no_env=True)
        assert r.exit_code == 0, r.output
        assert p.read_text() == OTHER
        assert not (tmp_path / "capella.yaml.bak").exists()


@pytest.mark.story("CAP-047", "AC3")
def test_configure_check_ac3_missing_project_reported(fake, run, write_config):
    seed_healthy(fake)
    write_config(TWO_PROJECTS)
    r = run("configure", input=f"{KEY}\n", no_env=True)
    assert r.exit_code == 0, r.output
    assert ("capella.yaml declares project free-proj, which is not in organization Nova Corp (projects: nova-dev)"
            in r.output)
    assert "project nova-dev, which" not in r.output
    assert "is for organization" not in r.output


@pytest.mark.story("CAP-047", "AC4")
def test_configure_check_ac4_matching_file_quiet(fake, run, write_config):
    seed_healthy(fake)
    for text in (MINIMAL.replace("${CAPELLA_ORG_ID}", "org-1"), MINIMAL):
        write_config(text)
        r = run("configure", input=f"{KEY}\n", no_env=True, extra_env={"CAPELLA_ORG_ID": "org-1"})
        assert r.exit_code == 0, r.output
        assert "capella.yaml already exists; to refresh it from Capella: capellactl import --force" in r.output
        assert "warning" not in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-047", "AC4")
def test_configure_check_ac4_unresolved_org_ref_quiet(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL)  # ${CAPELLA_ORG_ID} is not set: the profile supplies the organization
    r = run("configure", input=f"{KEY}\n", no_env=True)
    assert r.exit_code == 0, r.output
    assert "is for organization" not in r.output and "warning" not in r.output


@pytest.mark.story("CAP-047", "AC5")
def test_configure_check_ac5_import_refuses_other_org(fake, run, write_config, tmp_path):
    seed_healthy(fake)
    p = write_config(OTHER)
    r = run("import")
    assert r.exit_code == 3, r.output
    assert "capella.yaml is for organization org-other, not org-1" in r.output
    assert "--force" in r.output and "--file PATH" in r.output
    assert p.read_text() == OTHER
    r = run("import", "--stdout")
    assert r.exit_code == 0, r.output
    assert "organizationId: org-1" in r.output and p.read_text() == OTHER
    r = run("import", "--force")
    assert r.exit_code == 0, r.output
    assert yaml.safe_load(p.read_text())["organizationId"] == "org-1"
    assert (tmp_path / "capella.yaml.bak").read_text() == OTHER
