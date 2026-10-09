"""CAP-033 AC5: a newcomer reaches a first environment by following getting-started.md, start to finish.

Runs the guide's path for a new organization against the fake Capella, from an empty folder and an organization
with no projects: every step succeeds as written, nothing is edited by hand, and the end state is a healthy cluster
with a bucket and an application credential that a re-run leaves unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from capellactl.cli import console

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "getting-started.md"
KEY = "api-key-token-1234567890"
PW = {"ORDERS_APP_PASSWORD": "Orders-Passw0rd-2026!"}


def _guide_commands() -> str:
    text = GUIDE.read_text(encoding="utf-8")
    steps = text[text.index("## Step by step"):text.index("## capella.yaml: written by capellactl")]
    return "\n".join(re.findall(r"```bash\n(.*?)```", steps, flags=re.S))


def _end_state(fake, run, cfg):
    """A healthy cluster with a bucket and a credential, recorded in capella.yaml, and nothing left to do."""
    cluster = next(c for c in fake.clusters.values() if c["body"]["name"] == "nova-dev-01")
    assert fake.cluster_state(cluster["body"]["id"]) == "healthy"
    assert any(b["name"] == "orders" for (cid, _), b in fake.buckets.items() if cid == cluster["body"]["id"])
    assert any(u["name"] == "orders_app" for u in fake.users.values())
    text = cfg.read_text()
    assert "nova-dev-01" in text and "orders" in text and "${ORDERS_APP_PASSWORD}" in text
    assert "Orders-Passw0rd" not in text and KEY not in text  # no secret in the file
    fake.reset_calls()
    r = run("plan", "--detailed-exitcode", no_env=True, extra_env=PW)
    assert r.exit_code == 0, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-033", "AC5")
def test_docs_ac5_first_environment_from_scratch(fake, run, tmp_path, monkeypatch):
    """Guide steps 3 → 4 → 6 → 8 → 9: configure, create a project, deploy a cluster, add a bucket and a credential."""
    guide = _guide_commands()
    cfg = tmp_path / "capella.yaml"
    monkeypatch.setattr(console, "is_interactive", lambda: True)

    assert "capellactl configure" in guide                                                             # step 3
    r = run("configure", input=f"{KEY}\ny\n", no_env=True)
    assert r.exit_code == 0, r.output
    assert "profile 'default' saved" in r.output
    assert "This organization has no projects yet. Next: capellactl project create NAME" in r.output

    assert "capellactl project create" in guide                                                        # step 4
    r = run("project", "create", "nova-dev", "--description", "Nova development", input="y\n", no_env=True)
    assert r.exit_code == 0, r.output
    assert cfg.exists()

    assert "capellactl cluster create" in guide                                                        # step 6
    r = run("cluster", "create", "nova-dev-01", input="\n\n\n\n\n\ny\n", no_env=True)  # Enter: every default
    assert r.exit_code == 0, r.output
    assert "cluster nova-dev-01: healthy" in r.output

    assert "capellactl bucket create" in guide                                                         # step 8
    r = run("bucket", "create", "nova-dev-01", "orders", "--memory", "1024", input="y\n", no_env=True)
    assert r.exit_code == 0, r.output

    assert "capellactl credential create" in guide and "--password-env" in guide                     # step 9
    r = run("credential", "create", "nova-dev-01", "orders_app", "--privileges", "read+write", "--bucket", "orders",
            "--password-env", "ORDERS_APP_PASSWORD", input="y\n", no_env=True, extra_env=PW)
    assert r.exit_code == 0, r.output

    _end_state(fake, run, cfg)


@pytest.mark.story("CAP-033", "AC5")
def test_docs_ac5_first_environment_with_init(fake, run, tmp_path, monkeypatch):
    """The guide's "starting from scratch" path: init writes capella.yaml, then validate → plan → apply."""
    guide = _guide_commands()
    for cmd in ("capellactl init --non-interactive", "capellactl validate", "capellactl plan", "capellactl apply"):
        assert cmd in guide or cmd in GUIDE.read_text(), cmd
    cfg = tmp_path / "capella.yaml"
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    assert run("configure", input=f"{KEY}\nn\n", no_env=True).exit_code == 0

    monkeypatch.setattr(console, "is_interactive", lambda: False)  # the guide's scripted form of init
    r = run("init", "--non-interactive", "--project", "nova-dev", "--cluster", "nova-dev-01", "--provider", "aws",
            "--region", "us-east-1", "--preset", "small", "--bucket", "orders", "--bucket-memory", "1024",
            "--credential", "orders_app", "--access", "read-write", no_env=True)
    assert r.exit_code == 0, r.output
    assert run("validate", no_env=True, extra_env=PW).exit_code == 0
    r = run("plan", no_env=True, extra_env=PW)
    assert "+ cluster nova-dev-01" in r.output and "+ bucket nova-dev-01/orders" in r.output
    assert "+ credential nova-dev-01/orders_app" in r.output
    r = run("--auto-approve", "apply", no_env=True, extra_env=PW)
    assert r.exit_code == 0, r.output

    _end_state(fake, run, cfg)
