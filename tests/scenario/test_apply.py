"""CAP-006: apply executor, confirmation, output and exit codes."""
from __future__ import annotations

import pytest

from capellactl.cli import console
from tests.conftest import MINIMAL, seed_healthy
from tests.scenario.helpers import FULL, validate_json


def _kinds(fake):
    out = []
    for c in fake.writes():
        seg = c.path.rstrip("/").split("/")
        out.append((c.method, seg[-1] if c.method == "POST" else seg[-2]))
    return out


@pytest.mark.story("CAP-006", "AC1")
def test_apply_ac1_no_changes_no_prompt(fake, run, write_config, monkeypatch):
    seed_healthy(fake)
    write_config()
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("apply")  # no input given: a prompt would abort
    assert r.exit_code == 0
    assert "No changes. Capella matches capella.yaml." in r.output
    assert "Apply" not in r.output.replace("Apply complete", "")
    assert fake.writes() == []


@pytest.mark.story("CAP-006", "AC2")
def test_apply_ac2_decline_makes_no_writes(fake, run, write_config, monkeypatch):
    write_config()
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("apply", input="n\n")
    assert r.exit_code == 0
    assert "Apply 2 changes to project nova-dev? [y/N]" in r.output
    assert "Apply cancelled." in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-006", "AC2")
def test_apply_ac2_auto_approve(fake, run, write_config):
    write_config()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert len(fake.writes()) == 2


@pytest.mark.story("CAP-006", "AC2")
def test_apply_ac2_non_interactive_requires_flag(fake, run, write_config):
    write_config()
    r = run("apply")
    assert r.exit_code == 1
    assert "[ERROR]: refusing to apply without approval: there is no terminal to ask\n[ACTION]: Add --auto-approve" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-006", "AC3")
def test_apply_ac3_write_order(fake, run, write_config, stub_tree):
    write_config(FULL)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert _kinds(fake) == [("POST", "projects"), ("POST", "clusters"), ("POST", "allowedcidrs"),
                            ("POST", "buckets"), ("POST", "buckets"), ("POST", "scopes"), ("POST", "scopes"),
                            ("POST", "collections"), ("POST", "users")]
    paths = [c.path for c in fake.writes()]
    assert paths.index(next(p for p in paths if p.endswith("/users"))) > \
        paths.index(next(p for p in paths if p.endswith("/collections")))


@pytest.mark.story("CAP-006", "AC4")
def test_apply_ac4_blocked_prevents_any_write(fake, run, write_config, stub_tree):
    seed_healthy(fake)
    write_config(FULL.replace("us-east-1", "eu-west-1"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4
    assert "! cluster nova-dev-01  immutable: cloudProvider.region (requires a new cluster)" in r.output
    assert "[ERROR]: Apply refused: 1 blocked change(s); nothing was changed\n[ACTION]: Resolve each change marked !" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-006", "AC4")
def test_apply_ac4_target_excludes_blocked(fake, run, write_config, stub_tree):
    seed_healthy(fake)
    write_config(FULL.replace("us-east-1", "eu-west-1"))
    r = run("--auto-approve", "apply", "--target", "bucket/nova-dev-01/orders")
    assert r.exit_code == 0, r.output
    assert [c.path.split("/")[-1] for c in fake.writes()] == ["buckets", "scopes", "collections"]


@pytest.mark.story("CAP-006", "AC5")
def test_apply_ac5_failure_skips_rest(fake, run, write_config, stub_tree):
    seed_healthy(fake)
    fake.fail_next("POST", "*/buckets", 422)
    write_config(FULL)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 1
    assert "Failed: bucket nova-dev-01/events" in r.output
    assert "Completed before the failure: allowed-cidr nova-dev-01/203.0.113.10/32" in r.output
    assert "skipped" in r.output
    assert [c.path.split("/")[-1] for c in fake.writes()] == ["allowedcidrs", "buckets"]


@pytest.mark.story("CAP-006", "AC5")
def test_apply_ac5_rerun_resumes_without_duplicates(fake, run, write_config, stub_tree):
    seed_healthy(fake)
    fake.fail_next("POST", "*/scopes", 500)
    write_config(FULL)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 1 and "[ACTION]: Capella returned an internal error for this scope" in r.output, r.output
    assert run("--auto-approve", "apply").exit_code == 0
    posts = [c.path for c in fake.writes() if c.method == "POST"]
    for suffix in ("allowedcidrs", "users", "collections"):
        assert sum(p.endswith(suffix) for p in posts) == 1, suffix
    assert sum(p.endswith("/buckets") for p in posts) == 2  # events + orders, each once
    fake.reset_calls()
    assert run("--auto-approve", "apply").exit_code == 0
    assert fake.writes() == []


@pytest.mark.story("CAP-006", "AC6")
def test_apply_ac6_create_conflict_adopts_existing(fake, run, write_config, stub_tree):
    _, cid = seed_healthy(fake)
    fake.fail_next("POST", "*/buckets", 409, code=1010,
                   before=lambda: fake.seed_bucket(cid, "events", memoryAllocationInMb=512))
    write_config(FULL)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "bucket nova-dev-01/events already exists; using it" in r.output


@pytest.mark.story("CAP-006", "AC6")
def test_apply_ac6_412_replans_once(fake, run, write_config):
    seed_healthy(fake)
    fake.fail_next("PUT", "*/clusters/*", 412)
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert len(fake.calls("PUT", "*/clusters/*")) == 2


@pytest.mark.story("CAP-006", "AC6")
def test_apply_ac6_double_412_fails(fake, run, write_config):
    seed_healthy(fake)
    fake.fail_next("PUT", "*/clusters/*", 412, times=2)
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 1
    assert "cluster nova-dev-01 changed concurrently; re-run plan" in r.output


@pytest.mark.story("CAP-006", "AC6")
def test_apply_ac6_ambiguous_post_adopts_created(fake, run, write_config, stub_tree):
    import requests

    _, cid = seed_healthy(fake)
    fake.fail_next("POST", "*/allowedcidrs", exc=requests.exceptions.ReadTimeout("timed out"),
                   before=lambda: fake.cidrs.update({"cidr-9": {"id": "cidr-9", "_cluster": cid,
                                                                "cidr": "203.0.113.10/32", "comment": "Office VPN"}}))
    write_config(FULL)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "was created despite the lost response; using it" in r.output
    assert len(fake.calls("POST", "*/allowedcidrs")) == 1


@pytest.mark.story("CAP-006", "AC7")
def test_apply_ac7_json_schema(fake, run, write_config):
    write_config()
    r = run("-o", "json", "--auto-approve", "apply")
    assert r.exit_code == 0
    data = validate_json("apply.schema.json", r.stdout)
    assert data["result"]["status"] == "ok"
    assert [a["status"] for a in data["result"]["actions"]] == ["done", "done"]
    assert data["result"]["connectionStrings"][0].startswith("connectionString (nova-dev-01): couchbases://")


@pytest.mark.story("CAP-006", "AC8")
def test_apply_ac8_keyboard_interrupt_exit_130(fake, run, write_config):
    fake.seed_project("nova-dev", description="Nova development environment")
    fake.fail_next("POST", "*/clusters", exc=KeyboardInterrupt())
    write_config()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 130
    assert "[ERROR]: Interrupted\n[ACTION]: Run the command again to continue" in r.output
