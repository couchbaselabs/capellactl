"""CAP-013: deletion protection declared in capella.yaml, the shared delete guard and `cluster protect`."""
from __future__ import annotations

import pytest
import yaml

from capellactl.cli import console
from tests.conftest import MINIMAL, seed_healthy

PROTECTED = MINIMAL + "    deletionProtection: true\n"
ORDERS = "    buckets:\n      - name: orders\n        memoryAllocationInMb: 1024\n"
MESSAGE = "deletion protection is on for nova-dev-01; run 'capellactl cluster protect nova-dev-01 --off' first"


def _protection_puts(fake):
    return [c for c in fake.writes() if c.path.endswith("/deletionProtection")]


@pytest.mark.story("CAP-013", "AC1")
def test_protection_ac1_enable_from_config(fake, run, write_config):
    pid, cid = seed_healthy(fake)
    write_config(PROTECTED)
    r = run("plan")
    assert r.exit_code == 0, r.output
    assert "  ~ deletion-protection nova-dev-01" in r.output
    assert "      deletionProtection:  false → true" in r.output
    assert "Plan: 0 to add, 1 to change, 0 to delete, 0 blocked." in r.output
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert [(c.method, c.path, c.body) for c in fake.writes()] == [
        ("PUT", f"/v4/organizations/org-1/projects/{pid}/clusters/{cid}/deletionProtection",
         {"deletionProtection": True})]
    assert fake.clusters[cid]["body"]["deletionProtection"] is True


@pytest.mark.story("CAP-013", "AC2")
def test_protection_ac2_after_create_before_buckets(fake, run, write_config):
    fake.seed_project("nova-dev", description="Nova development environment")
    write_config(PROTECTED + ORDERS)
    r = run("plan")
    assert "  + deletion-protection nova-dev-01  deletionProtection: true  (after cluster is healthy)" in r.output
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    writes = [(c.method, c.path.rsplit("/", 1)[-1]) for c in fake.writes()]
    assert writes == [("POST", "clusters"), ("PUT", "deletionProtection"), ("POST", "buckets")]
    assert r.output.index("cluster nova-dev-01: healthy") < r.output.index("creating deletion-protection nova-dev-01")


@pytest.mark.story("CAP-013", "AC3")
@pytest.mark.parametrize("current", [True, False])
def test_protection_ac3_omitted_unchanged_plan(fake, run, write_config, current):
    seed_healthy(fake, deletionProtection=current)
    write_config(MINIMAL)
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0, r.output
    assert "deletion-protection" not in r.output


@pytest.mark.story("CAP-013", "AC4")
@pytest.mark.parametrize("command", [
    ("cluster", "delete", "nova-dev-01"),
    ("bucket", "delete", "nova-dev-01", "orders"),
    ("destroy",),
    ("apply", "--prune"),
    ("project", "delete", "nova-dev", "--cascade"),
], ids=["cluster-delete", "bucket-delete", "destroy", "apply-prune", "project-delete-cascade"])
def test_protection_ac4_blocks_all_delete_paths(fake, run, write_config, command):
    _, cid = seed_healthy(fake, deletionProtection=True)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=1024)
    write_config(MINIMAL)  # orders is not declared: apply --prune would delete it
    r = run("--auto-approve", *command)
    assert r.exit_code == 4, r.output
    assert MESSAGE in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-013", "AC5")
def test_protection_cli_ac5_off_records_in_file(fake, run, write_config, tmp_path):
    pid, cid = seed_healthy(fake, deletionProtection=True)
    write_config(PROTECTED)
    r = run("--auto-approve", "cluster", "protect", "nova-dev-01", "--off")
    assert r.exit_code == 0, r.output
    assert "deletion protection off for nova-dev-01" in r.output
    assert "capella.yaml updated: deletionProtection removed for nova-dev-01" in r.output
    assert "deletionProtection" not in (tmp_path / "capella.yaml").read_text()
    assert [(c.method, c.path, c.body) for c in fake.writes()] == [
        ("PUT", f"/v4/organizations/org-1/projects/{pid}/clusters/{cid}/deletionProtection",
         {"deletionProtection": False})]


@pytest.mark.story("CAP-013", "AC5")
def test_protection_cli_ac5_already_off_noop(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL)
    r = run("cluster", "protect", "nova-dev-01", "--off")
    assert r.exit_code == 0, r.output
    assert "deletion protection is already off for nova-dev-01; nothing to do" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-013", "AC5")
def test_protection_cli_ac5_on_and_confirmation(fake, run, write_config, monkeypatch):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL)
    r = run("cluster", "protect", "nova-dev-01", "--on")  # turning it on needs no confirmation
    assert r.exit_code == 0 and "deletion protection on for nova-dev-01" in r.output, r.output
    assert fake.clusters[cid]["body"]["deletionProtection"] is True
    fake.reset_calls()
    r = run("cluster", "protect", "nova-dev-01", "--off")  # turning it off does, and refuses without a terminal
    assert r.exit_code == 1 and "--auto-approve" in r.output
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "protect", "nova-dev-01", "--off", input="n\n")
    assert "Cancelled; deletion protection is unchanged." in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-013", "AC6")
def test_protection_ac6_rerun_zero_writes(fake, run, write_config):
    seed_healthy(fake)
    write_config(PROTECTED)
    assert run("--auto-approve", "apply").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0 and "No changes" in r.output, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-013", "AC5")
def test_protection_cli_ac5_on_records_in_file(fake, run, tmp_path):
    seed_healthy(fake)
    assert run("import").exit_code == 0
    r = run("cluster", "protect", "nova-dev-01", "--on")
    assert r.exit_code == 0, r.output
    assert "capella.yaml updated: deletionProtection: true for nova-dev-01" in r.output
    cfg = yaml.safe_load((tmp_path / "capella.yaml").read_text())
    assert cfg["projects"][0]["clusters"][0]["deletionProtection"] is True
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output and fake.writes() == []
    assert "already in sync" in run("sync").output
    r = run("cluster", "protect", "nova-dev-01", "--on")  # already on, already recorded: nothing to do anywhere
    assert "already on" in r.output and "updated" not in r.output
