"""The getting-started guide's steps keep working, and never ask the user to edit capella.yaml."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from capellactl.cli import console
from tests.conftest import seed_healthy

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "getting-started.md"


def _steps_section() -> str:
    text = GUIDE.read_text(encoding="utf-8")
    return text[text.index("## Step by step"):text.index("## capella.yaml: written by capellactl")]


@pytest.mark.story("CAP-038", "AC12")
def test_readme_ac12_no_manual_edit_steps():
    steps = _steps_section()
    for bad in (r"\bedit (the|your|this)? ?(file|capella\.yaml)\b(?! by hand)", r"in `capella\.yaml`, change",
                r"add an entry under", r"uncomment", r"open capella\.yaml"):
        assert not re.search(bad, steps, flags=re.I), f"guide step asks for a manual edit: /{bad}/"
    for cmd in ("capellactl configure", "capellactl cluster create", "capellactl cluster scale",
                "capellactl cluster update", "capellactl bucket create", "capellactl bucket update",
                "capellactl bucket delete", "capellactl scope create", "capellactl collection create",
                "capellactl collection update", "capellactl scope delete", "capellactl sync", "capellactl init", "capellactl cluster protect",
                "capellactl cidr create", "capellactl cidr delete", "capellactl cluster delete",
                "capellactl credential create", "capellactl credential update", "capellactl credential delete"):
        assert cmd in steps


@pytest.mark.story("CAP-038", "AC12")
def test_readme_walkthrough_steps(fake, run, tmp_path, monkeypatch):
    _, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=1024)
    cfg = tmp_path / "capella.yaml"

    monkeypatch.setattr(console, "is_interactive", lambda: True)                                      # step 3
    r = run("configure", input="api-key-token-1234567890\ny\n", no_env=True)
    assert r.exit_code == 0 and "Imported 1 project, 1 cluster, 1 bucket" in r.output and cfg.exists()

    r = run("plan", "--detailed-exitcode", no_env=True)                                               # step 4
    assert r.exit_code == 0 and "= cluster nova-dev-01" in r.output

    r = run("cluster", "create", "nova-dev-02", input="\n\n\n\n\n\ny\n", no_env=True)                    # step 5
    assert r.exit_code == 0 and "cluster nova-dev-02: healthy" in r.output, r.output
    monkeypatch.setattr(console, "is_interactive", lambda: False)
    assert run("--auto-approve", "cluster", "create", "nova-qa-01", "--provider", "gcp", "--size", "medium",
               "--support-plan", "enterprise", no_env=True).exit_code == 0

    for args in (("cluster", "scale", "nova-dev-01", "--nodes", "4"),                                  # step 6
                 ("cluster", "update", "nova-dev-01", "--support-plan", "enterprise"),
                 ("cluster", "update", "nova-dev-01", "--cpu", "8", "--ram", "32")):
        assert run("--auto-approve", *args, no_env=True).exit_code == 0, args
    assert "No changes" in run("--auto-approve", "apply", no_env=True).output

    r = run("--auto-approve", "bucket", "create", "nova-dev-01", "events", "--memory", "1024",          # step 8
            "--storage-backend", "magma", "--durability", "majority", no_env=True)
    assert "+ bucket nova-dev-01/events  couchbase · magma · 1024 MB · 1 replica · durability majority" in r.output
    assert run("--auto-approve", "bucket", "update", "nova-dev-01", "events", "--memory", "2048",
               no_env=True).exit_code == 0
    assert "events" in run("bucket", "list", "nova-dev-01", no_env=True).output
    r = run("--auto-approve", "bucket", "delete", "nova-dev-01", "events", no_env=True)
    assert r.exit_code == 0 and "deleted bucket nova-dev-01/events" in r.output
    assert run("--auto-approve", "scope", "create", "nova-dev-01", "orders", "billing", no_env=True).exit_code == 0
    r = run("--auto-approve", "collection", "create", "nova-dev-01", "orders", "billing", "invoices", "--max-ttl",
            "2592000", no_env=True)
    assert r.exit_code == 0 and "+ collection nova-dev-01/orders/billing/invoices  maxTTL 2592000" in r.output
    assert run("--auto-approve", "collection", "update", "nova-dev-01", "orders", "billing", "invoices",
               "--max-ttl", "-1", no_env=True).exit_code == 0
    assert "invoices" in run("collection", "list", "nova-dev-01", "orders", "billing", no_env=True).output
    r = run("--auto-approve", "scope", "delete", "nova-dev-01", "orders", "billing", no_env=True)
    assert r.exit_code == 0 and "deleted scope nova-dev-01/orders/billing" in r.output
    assert "No changes" in run("--auto-approve", "apply", no_env=True).output

    pw = {"ORDERS_APP_PW": "Orders-Passw0rd-2026!"}
    r = run("--auto-approve", "credential", "create", "nova-dev-01", "orders_app", "--privileges",        # step 9
            "read+write", "--bucket", "orders", "--password-env", "ORDERS_APP_PW", extra_env=pw, no_env=True)
    assert r.exit_code == 0 and "+ credential nova-dev-01/orders_app  read+write · orders" in r.output, r.output
    assert "${ORDERS_APP_PW}" in cfg.read_text() and "Orders-Passw0rd" not in cfg.read_text()
    assert "orders_app" in run("credential", "list", "nova-dev-01", extra_env=pw, no_env=True).output
    pw = {"ORDERS_APP_PW": "Orders-Passw0rd-2026-v2!"}
    r = run("--auto-approve", "credential", "update", "nova-dev-01", "orders_app", "--rotate-password", extra_env=pw,
            no_env=True)
    assert r.exit_code == 0 and "password rotated for orders_app" in r.output
    r = run("--auto-approve", "credential", "delete", "nova-dev-01", "orders_app", extra_env=pw, no_env=True)
    assert r.exit_code == 0, r.output
    assert "No changes" in run("--auto-approve", "apply", no_env=True).output

    assert run("--auto-approve", "cluster", "protect", "nova-dev-01", "--on", no_env=True).exit_code == 0  # step 10
    r = run("--auto-approve", "cidr", "create", "nova-dev-01", "203.0.113.10/32", "--comment", "Office VPN", no_env=True)
    assert r.exit_code == 0 and "203.0.113.10/32" in run("cidr", "list", "nova-dev-01", no_env=True).output
    assert run("--auto-approve", "cidr", "delete", "nova-dev-01", "203.0.113.10/32", no_env=True).exit_code == 0
    assert run("--auto-approve", "cluster", "delete", "nova-dev-02", no_env=True).exit_code == 0
    r = run("--auto-approve", "cluster", "delete", "nova-dev-01", no_env=True)
    assert r.exit_code == 4 and "deletion protection is on for nova-dev-01" in r.output
    assert run("--auto-approve", "cluster", "protect", "nova-dev-01", "--off", no_env=True).exit_code == 0
    assert "No changes" in run("--auto-approve", "apply", no_env=True).output

    fake.clusters[cid]["body"]["description"] = "changed in the Capella UI"                            # step 11
    assert run("sync", "--dry-run", no_env=True).exit_code == 2
    r = run("sync", no_env=True)
    assert "+    description: changed in the Capella UI" in r.output
    assert "already in sync" in run("sync", no_env=True).output

    def ok(*args: str) -> str:
        r = run("--auto-approve", *args, no_env=True)
        assert r.exit_code == 0, (args, r.output)
        return str(r.output)

    assert "is off (storage, data and configuration retained)" in ok("cluster", "power", "nova-dev-01", "--off")  # 12
    assert "cluster nova-dev-01 is on" in ok("cluster", "power", "nova-dev-01", "--on")
    assert "+ schedule nova-dev-01  US/Pacific" in ok("cluster", "schedule", "set", "nova-dev-01", "--timezone",
                                                      "US/Pacific", "--weekdays", "08:00-18:00", "--weekend", "off")
    assert "Next: " in ok("cluster", "schedule", "show", "nova-dev-01")
    assert "schedule paused" in ok("cluster", "schedule", "pause", "nova-dev-01", "--power-on")
    assert "schedule resumed" in ok("cluster", "schedule", "resume", "nova-dev-01")
    assert "scaled data,index,query: 4 → 5" in ok("cluster", "scale", "nova-dev-01", "--step", "+1", "--max", "6")
    assert "checks: memory ok" in ok("cluster", "scale", "nova-dev-01", "--step", "-1", "--min", "3")

    r = run("drift", "--detailed-exitcode", no_env=True)                                               # step 13
    assert r.exit_code in (0, 2) and "Drift" in r.output or "No drift" in r.output, r.output
    ok("apply", "--prune")
    assert "No drift" in run("drift", no_env=True).output
    ok("cluster", "protect", "nova-dev-01", "--off")
    r = run("--auto-approve", "destroy", no_env=True)
    assert r.exit_code == 0 and "Destroy complete" in r.output, r.output

    r = run("--auto-approve", "apply", no_env=True)                                                    # step 14
    assert r.exit_code == 0, r.output  # capella.yaml was kept: apply builds it again
    write = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "4", no_env=True)
    assert write.exit_code == 0, write.output
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "3", no_env=True)
    assert r.exit_code == 0 and "checks: memory ok" in r.output, r.output  # scale-in with capacity checks
