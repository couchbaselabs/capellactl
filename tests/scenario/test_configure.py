"""CAP-037: configure, profiles and keychain."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import keyring
import pytest
import yaml
from keyring.backends import fail

from capellactl.config.settings import profiles_path
from tests.conftest import assert_no_secret, seed_healthy

KEY = "profile-key-0987654321"


@pytest.mark.story("CAP-037", "AC1")
def test_configure_ac1_saves_profile_and_keychain(fake, run, keychain, monkeypatch):
    from capellactl.cli import console as console_mod

    monkeypatch.setattr(console_mod, "is_interactive", lambda: True)
    fake.orgs["org-2"] = {"id": "org-2", "name": "Nova Labs", "description": ""}
    r = run("configure", input=f"{KEY}\n2\nn\n", no_env=True)
    assert r.exit_code == 0, r.output
    assert "profile 'default' saved (org Nova Labs)" in r.output
    p = profiles_path()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["profiles"]["default"]["organizationId"] == "org-2"
    assert keychain.store[("capellactl", "default")] == KEY
    if os.name == "posix":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert fake.calls("GET", "/v4/organizations")[0].headers["Authorization"] == f"Bearer {KEY}"


@pytest.mark.story("CAP-037", "AC1")
def test_configure_ac1_key_not_echoed(fake, run):
    r = run("configure", "--api-key-stdin", input=f"{KEY}\n", no_env=True)
    assert r.exit_code == 0
    assert_no_secret(r.output, KEY)
    assert_no_secret(profiles_path().read_text(encoding="utf-8"), KEY)


@pytest.mark.story("CAP-055", "AC4")
def test_windows_docs_ac4_powershell_piped_key_stored_clean(fake, run, keychain):
    r = run("configure", "--api-key-stdin", input=f"﻿{KEY}\r\n", no_env=True)       # Get-Clipboard | …
    assert r.exit_code == 0, r.output
    assert keychain.store[("capellactl", "default")] == KEY
    assert fake.calls("GET", "/v4/organizations")[0].headers["Authorization"] == f"Bearer {KEY}"


@pytest.mark.story("CAP-037", "AC2")
def test_configure_ac2_invalid_key_not_saved(fake, run, keychain):
    fake.api_keys = {"the-real-key"}
    r = run("configure", "--api-key-stdin", input="wrong-key-123\n", no_env=True)
    assert r.exit_code == 1
    assert "API Key Token rejected" in r.output
    assert not profiles_path().exists()
    assert keychain.store == {}


@pytest.mark.story("CAP-037", "AC3")
def test_configure_ac3_show_sources(fake, run):
    run("configure", "--api-key-stdin", input=f"{KEY}\n", no_env=True)
    r = run("configure", "show", no_env=True)
    assert r.exit_code == 0
    assert "organization" in r.output and "org-1" in r.output and "(profile default)" in r.output
    assert "••••4321" in r.output and "keychain (profile default)" in r.output
    assert_no_secret(r.output, KEY)
    r = run("configure", "show", no_env=True, extra_env={"CAPELLA_ORG_ID": "org-env"})
    assert "org-env" in r.output and "(CAPELLA_ORG_ID)" in r.output


@pytest.mark.story("CAP-037", "AC3")
def test_configure_ac3_profile_used_by_commands(fake, run, write_config):
    run("configure", "--api-key-stdin", input=f"{KEY}\n", no_env=True)
    write_config()
    r = run("plan", no_env=True)
    assert r.exit_code == 0, r.output
    assert fake.calls("GET", "*/projects")[0].headers["Authorization"] == f"Bearer {KEY}"


@pytest.mark.story("CAP-037", "AC4")
def test_configure_ac4_no_keychain_never_writes_key(fake, run, tmp_path):
    keyring.set_keyring(fail.Keyring())
    r = run("configure", "--api-key-stdin", input=f"{KEY}\n", no_env=True)
    assert r.exit_code == 0
    assert "no OS keychain available; set CAPELLA_API_KEY" in r.output
    for f in Path(tmp_path).rglob("*"):
        if f.is_file():
            assert KEY not in f.read_text(errors="ignore", encoding="utf-8"), f


@pytest.mark.story("CAP-037", "AC6")
def test_configure_ac6_remove_profile_and_key(fake, run, keychain):
    run("configure", "--profile", "dev", "--api-key-stdin", input=f"{KEY}\n", no_env=True)
    assert ("capellactl", "dev") in keychain.store
    r = run("configure", "remove", "--profile", "dev", no_env=True)  # the documented form
    assert r.exit_code == 0 and "profile 'dev' removed (keychain entry deleted)" in r.output
    assert ("capellactl", "dev") not in keychain.store
    assert "dev" not in (yaml.safe_load(profiles_path().read_text(encoding="utf-8"))["profiles"])
    r = run("configure", "--profile", "dev", "remove", no_env=True)  # --profile before the subcommand also works
    assert r.exit_code == 0 and "nothing to remove" in r.output


@pytest.mark.story("CAP-037", "AC6")
def test_configure_ac6_list(fake, run):
    run("configure", "--profile", "dev", "--api-key-stdin", input=f"{KEY}\n", no_env=True)
    r = run("configure", "list", no_env=True)
    assert "dev" in r.output and "Nova Corp (org-1)" in r.output and "keychain" in r.output


@pytest.mark.story("CAP-037", "AC7")
def test_configure_ac7_rejection_shows_hint_and_checklist(fake, run, keychain):
    fake.api_keys = {"the-real-key"}
    r = run("configure", "--api-key-stdin", input="Bearer wrong-key-abcd\n", no_env=True)
    assert r.exit_code == 1
    for s in ("API Key Token rejected by Capella (HTTP 401: Unauthorized); nothing was saved.",
              "the API key allowlist", "has 14 characters and ends in …abcd",
              "allowed IP list", "not the API Key ID or name", "curl -s -o /dev/null", "--api-key-stdin",
              "note: removed a leading 'Bearer ' from the pasted key"):
        assert s in r.output, s
    assert_no_secret(r.output, "wrong-key-abcd")
    assert not profiles_path().exists() and keychain.store == {}


@pytest.mark.story("CAP-037", "AC7")
def test_configure_ac7_api_key_stdin(fake, run, keychain):
    r = run("configure", "--api-key-stdin", input=f"{KEY}\n", no_env=True)
    assert r.exit_code == 0, r.output
    assert keychain.store[("capellactl", "default")] == KEY
    fake.orgs["org-2"] = {"id": "org-2", "name": "Nova Labs", "description": ""}
    r = run("configure", "--profile", "two", "--api-key-stdin", input=KEY, no_env=True)
    assert r.exit_code == 3 and "pass --org-id ID" in r.output and "Nova Labs (org-2)" in r.output
    r = run("configure", "--profile", "two", "--api-key-stdin", "--org-id", "org-2", input=KEY, no_env=True)
    assert r.exit_code == 0 and "profile 'two' saved (org Nova Labs)" in r.output


def test_configure_offers_import_and_writes_capella_yaml(fake, run, tmp_path, monkeypatch):
    from capellactl.cli import console as console_mod

    seed_healthy(fake)
    monkeypatch.setattr(console_mod, "is_interactive", lambda: True)
    r = run("configure", input=f"{KEY}\ny\n", no_env=True)
    assert r.exit_code == 0, r.output
    assert "Discover your projects and clusters and write capella.yaml now?" in r.output
    assert "Imported 1 project, 1 cluster" in r.output
    assert (tmp_path / "capella.yaml").exists()
    r = run("plan", "--detailed-exitcode", no_env=True)
    assert r.exit_code == 0, r.output


def test_configure_non_interactive_prints_next_step(fake, run, tmp_path):
    seed_healthy(fake)
    r = run("configure", "--api-key-stdin", input=f"{KEY}\n", no_env=True)
    assert "Next: capellactl sync" in r.output and not (tmp_path / "capella.yaml").exists()
    r = run("configure", "--import", "--api-key-stdin", input=f"{KEY}\n", no_env=True)
    assert "Imported 1 project, 1 cluster" in r.output and (tmp_path / "capella.yaml").exists()
