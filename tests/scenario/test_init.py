"""CAP-035: `capellactl init` writes a valid, commented capella.yaml from a few answers."""
from __future__ import annotations

from pathlib import Path

import pytest

from capellactl.cli import console
from tests.conftest import API_KEY, assert_no_secret, seed_healthy

GOLDEN = Path(__file__).parent / "fixtures" / "init_capella.yaml"
PASSWORD = "Orders#App-Secret-42"

# The interactive flow, one answer per question ("" takes the default).
FLOW = [
    ("start", ""), ("project", "nova-dev"), ("cluster", ""), ("provider", ""), ("region", ""), ("network", ""),
    ("preset", ""), ("support", ""), ("protect", ""), ("hibernate", "y"), ("window", ""), ("timezone", ""),
    ("cidrs", "203.0.113.10/32"), ("bucket", "orders"), ("memory", ""), ("backend", ""),
    ("scopes", "inventory:items,suppliers;billing:invoices"), ("credential", "orders_app"), ("access", ""),
    ("password_env", ""),
]
FLAGS = ["--project", "nova-dev", "--cluster", "nova-dev-01", "--provider", "aws", "--region", "us-east-1",
         "--preset", "small", "--hibernation", "office-hours", "--timezone", "US/Pacific", "--cidr", "203.0.113.10/32",
         "--bucket", "orders", "--scope", "inventory:items,suppliers", "--scope", "billing:invoices",
         "--credential", "orders_app"]


def answers(**override: str | list[str]) -> str:
    """Input for CliRunner; an override list answers the same question several times (re-asked)."""
    lines: list[str] = []
    for key, value in FLOW:
        v = override.get(key, value)
        lines += v if isinstance(v, list) else [v]
    return "\n".join(lines) + "\n"


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)


@pytest.mark.story("CAP-035", "AC1")
def test_init_ac1_interactive_writes_valid_file(fake, run, tmp_path, tty):
    r = run("init", input=answers())
    assert r.exit_code == 0, r.output
    text = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert text == GOLDEN.read_text(encoding="utf-8")
    assert "✔ Wrote capella.yaml (validated)" in r.output
    assert "Next: export ORDERS_APP_PASSWORD=…   then   capellactl plan" in r.output
    r = run("validate", extra_env={"ORDERS_APP_PASSWORD": PASSWORD})
    assert r.exit_code == 0, r.output
    assert "1 cluster, 1 bucket, 2 scopes, 3 collections, 1 credential, 1 allowed CIDR, 1 hibernation schedule" \
        in r.output


@pytest.mark.story("CAP-035", "AC2")
def test_init_ac2_lists_orgs_and_projects(fake, run, tmp_path, tty):
    fake.orgs["org-2"] = {"id": "org-2", "name": "Other Corp", "description": ""}
    first = fake.seed_project("nova-dev")
    second = fake.seed_project("nova-dev")
    fake.seed_project("nova-qa")
    # organization 1 (Nova Corp), then project 2 (the second nova-dev: the name is ambiguous, so it is pinned)
    r = run("init", input=answers(start=["", "1"], project="2"))
    assert r.exit_code == 0, r.output
    assert "  1. Nova Corp (org-1)" in r.output and "  2. Other Corp (org-2)" in r.output
    assert "  3. nova-qa" in r.output
    text = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert f"project:\n  id: {second}\n  name: nova-dev\n" in text and first not in text
    r = run("--auto-approve", "init", "--force", input=answers(start=["", "1"], project="3"))
    text = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert "project:\n  name: nova-qa\n" in text  # unique name: no id: pin
    assert any(c.path == "/v4/organizations" for c in fake.calls("GET"))
    assert any(c.path == "/v4/organizations/org-1/projects" for c in fake.calls("GET"))


@pytest.mark.story("CAP-035", "AC2")
def test_init_ac2_without_key_typed_org(fake, run, tmp_path, tty):
    r = run("init", input=answers(start=["", "org-9"]), no_env=True)
    assert r.exit_code == 0, r.output
    assert "run 'capellactl configure'" in r.output
    assert "organizationId: org-9\n" in (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert fake.calls() == []


@pytest.mark.story("CAP-035", "AC2")
def test_init_ac2_never_writes_to_capella(fake, run, tty):
    seed_healthy(fake)
    assert run("init", input=answers(project="1", cluster="nova-dev-02")).exit_code == 0
    assert fake.writes() == []


@pytest.mark.story("CAP-035", "AC2")
def test_init_ac2_existing_cluster_name_reasked(fake, run, tmp_path, tty):
    seed_healthy(fake)
    r = run("init", input=answers(project="1", cluster=["", "nova-dev-02"]))
    assert r.exit_code == 0, r.output
    assert "cluster nova-dev-01 already exists in project nova-dev" in r.output
    text = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert "- name: nova-dev-02" in text
    assert "cidr: 10.0.0.0/24" in text  # the first free /24; nova-dev-01 uses 10.10.0.0/24


@pytest.mark.story("CAP-035", "AC4")
def test_init_ac4_no_secrets_in_file(fake, run, tmp_path, tty):
    r = run("init", input=answers(), extra_env={"ORDERS_APP_PASSWORD": PASSWORD})
    assert r.exit_code == 0, r.output
    text = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert "password: ${ORDERS_APP_PASSWORD}" in text
    assert_no_secret(text, API_KEY, PASSWORD)
    assert_no_secret(r.output, API_KEY, PASSWORD)


@pytest.mark.story("CAP-035", "AC5")
def test_init_ac5_existing_file_prompt(fake, run, tmp_path, tty):
    (tmp_path / "capella.yaml").write_text("# mine\n", encoding="utf-8")
    r = run("init", input="n\n")
    assert r.exit_code == 0
    assert "capella.yaml exists. Overwrite? [y/N]" in r.output and "Nothing was written." in r.output
    assert (tmp_path / "capella.yaml").read_text(encoding="utf-8") == "# mine\n"
    assert fake.calls() == []


@pytest.mark.story("CAP-035", "AC5")
def test_init_ac5_non_interactive_requires_force(fake, run, tmp_path):
    (tmp_path / "capella.yaml").write_text("# mine\n", encoding="utf-8")
    r = run("init", "--non-interactive", *FLAGS)
    assert r.exit_code == 1 and "pass --force" in r.output
    assert (tmp_path / "capella.yaml").read_text(encoding="utf-8") == "# mine\n"


@pytest.mark.story("CAP-035", "AC5")
def test_init_ac5_backup_written(fake, run, tmp_path, tty):
    (tmp_path / "capella.yaml").write_text("# mine\n", encoding="utf-8")
    r = run("init", input="y\n" + answers())
    assert r.exit_code == 0, r.output
    assert (tmp_path / "capella.yaml.bak").read_text(encoding="utf-8") == "# mine\n"
    assert (tmp_path / "capella.yaml").read_text(encoding="utf-8") == GOLDEN.read_text(encoding="utf-8")


@pytest.mark.story("CAP-035", "AC6")
@pytest.mark.parametrize(("question", "bad", "message"), [
    ("cluster", "x" * 257, "clusters[0].name: must be at most 256 characters"),
    ("cidrs", "10.0.0.5/24", "10.0.0.5/24 is not a network address (did you mean 10.0.0.0/24?)"),
    ("window", "08:15-18:00", "clusters[0].hibernation.weekdays: start minute must be 00 or 30 (got 08:15)"),
], ids=["cluster-name", "cidr-host-bits", "schedule-minute"])
def test_init_ac6_invalid_answers_reprompted(fake, run, tmp_path, tty, question, bad, message):
    good = dict(FLOW)[question]
    r = run("init", input=answers(**{question: [bad, good]}))
    assert r.exit_code == 0, r.output
    assert message in r.output
    assert "Please answer again." in r.output
    assert (tmp_path / "capella.yaml").read_text(encoding="utf-8") == GOLDEN.read_text(encoding="utf-8")


@pytest.mark.story("CAP-035", "AC7")
def test_init_ac7_non_interactive_matches_interactive(fake, run, tmp_path):
    r = run("init", "--non-interactive", *FLAGS)
    assert r.exit_code == 0, r.output
    assert (tmp_path / "capella.yaml").read_text(encoding="utf-8") == GOLDEN.read_text(encoding="utf-8")
    assert fake.writes() == []


@pytest.mark.story("CAP-035", "AC7")
def test_init_ac7_dry_run_stdout_only(fake, run, tmp_path):
    r = run("init", "--non-interactive", "--dry-run", *FLAGS)
    assert r.exit_code == 0, r.output
    assert GOLDEN.read_text(encoding="utf-8").rstrip("\n") in r.stdout
    assert not (tmp_path / "capella.yaml").exists()


@pytest.mark.story("CAP-035", "AC7")
def test_init_ac7_missing_flags(fake, run, tmp_path):
    r = run("init", "--non-interactive", "--provider", "aws")
    assert r.exit_code == 3
    assert "missing required options for --non-interactive: --project, --cluster" in r.output
    r = run("init", "--non-interactive", "--project", "p", "--cluster", "c", no_env=True)
    assert r.exit_code == 3 and "--org-id" in r.output
    assert not (tmp_path / "capella.yaml").exists()


@pytest.mark.story("CAP-035", "AC8")
def test_init_ac8_delegates_to_import(fake, run, tmp_path, tty):
    pid, cid = seed_healthy(fake)
    fake.seed_cluster(pid, "nova-dev-02")
    r = run("init", input="import\n1\nnova-dev-01\n")
    assert r.exit_code == 0, r.output
    assert "Imported 1 project, 1 cluster" in r.output
    text = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert "name: nova-dev-01" in text and "nova-dev-02" not in text
    assert fake.writes() == []
    assert run("plan", "--detailed-exitcode").exit_code == 0


@pytest.mark.story("CAP-035", "AC9")
def test_init_ac9_plan_after_init(fake, run, tty):
    assert run("init", input=answers()).exit_code == 0
    r = run("plan", extra_env={"ORDERS_APP_PASSWORD": PASSWORD})
    assert r.exit_code == 0, r.output
    actions = [line for line in r.output.splitlines() if line.startswith("  ") and not line.startswith("   ")]
    assert actions and {line[2] for line in actions} <= {"+", "…"}, actions  # … = kinds this build defers
    for kind in ("project nova-dev", "cluster nova-dev-01", "deletion-protection nova-dev-01",
                 "allowed-cidr nova-dev-01/203.0.113.10/32", "bucket nova-dev-01/orders"):
        assert f"  + {kind}" in r.output
    assert "0 to change, 0 to delete, 0 blocked" in r.output
