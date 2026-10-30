"""CAP-042: non-interactive (CI/CD) mode for every command."""
from __future__ import annotations

import json
import time

import pytest

from capellactl.cli import console
from tests.conftest import seed_healthy
from tests.scenario.helpers import seed_user

ORDERS_ACCESS = [{"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders"}]}}]

# Every command that changes Capella or capella.yaml, with arguments that make it change something in the
# environment built by `_environment`, and the verb of its refusal.
WRITE_COMMANDS = [
    (["project", "create", "nova-qa"], "create a project"),
    (["project", "update", "nova-dev", "--description", "CI"], "change capella.yaml and Capella"),
    (["cluster", "create", "nova-dev-02"], "change capella.yaml and Capella"),
    (["cluster", "update", "nova-dev-01", "--description", "CI"], "change capella.yaml and Capella"),
    (["cluster", "scale", "nova-dev-01", "--nodes", "4"], "change capella.yaml and Capella"),
    (["cluster", "power", "nova-dev-01", "--off"], "turn off a cluster"),
    (["cluster", "schedule", "set", "nova-dev-01", "--timezone", "US/Pacific", "--weekdays", "08:00-18:00"],
     "change capella.yaml and Capella"),
    (["bucket", "create", "nova-dev-01", "events", "--memory", "256"], "change capella.yaml and Capella"),
    (["bucket", "update", "nova-dev-01", "orders", "--memory", "512"], "change capella.yaml and Capella"),
    (["bucket", "delete", "nova-dev-01", "orders"], "delete a bucket"),
    (["scope", "create", "nova-dev-01", "orders", "billing"], "change capella.yaml and Capella"),
    (["scope", "delete", "nova-dev-01", "orders", "inventory"], "delete a scope"),
    (["collection", "create", "nova-dev-01", "orders", "inventory", "suppliers"], "change capella.yaml and Capella"),
    (["collection", "update", "nova-dev-01", "orders", "inventory", "items", "--max-ttl", "60"],
     "change capella.yaml and Capella"),
    (["collection", "delete", "nova-dev-01", "orders", "inventory", "items"], "delete a collection"),
    (["cidr", "create", "nova-dev-01", "198.51.100.0/24"], "change capella.yaml and Capella"),
    (["cidr", "delete", "nova-dev-01", "203.0.113.10/32"], "delete an allowed CIDR"),
    (["credential", "create", "nova-dev-01", "reports", "--privileges", "read", "--bucket", "orders"],
     "change capella.yaml and Capella"),
    (["credential", "delete", "nova-dev-01", "orders_ro"], "delete a database credential"),
    (["cluster", "delete", "nova-dev-01"], "delete a cluster"),
    (["project", "delete", "nova-dev", "--cascade"], "delete a project"),
    (["destroy"], "destroy"),
    (["apply", "--prune"], "apply"),
]
IDS = [" ".join(a[:3]) for a, _ in WRITE_COMMANDS]


@pytest.fixture
def environment(fake, run, tmp_path):
    """A healthy cluster with a bucket, scope, collection, allowed CIDR and credential, imported into capella.yaml;
    plus a stray bucket in Capella only, for `apply --prune`."""
    pid, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders")
    fake.seed_scope(cid, "orders", "inventory", {"items": 0})
    i = f"cidr-{len(fake.cidrs) + 100}"
    fake.cidrs[i] = {"id": i, "_cluster": cid, "cidr": "203.0.113.10/32", "status": "active", "comment": "VPN"}
    seed_user(fake, cid, "orders_ro", ORDERS_ACCESS)
    assert run("import").exit_code == 0
    fake.seed_bucket(cid, "stray")
    fake.reset_calls()
    return tmp_path / "capella.yaml"


@pytest.mark.story("CAP-042", "AC1")
@pytest.mark.parametrize("args,verb", WRITE_COMMANDS, ids=IDS)
def test_ci_ac1_flag_approves_every_write_command(fake, run, environment, args, verb):
    r = run("--auto-approve", *args)
    assert r.exit_code == 0, r.output
    assert fake.writes(), "the command changed nothing in Capella"
    assert "Type the" not in r.output and "[y/N]" not in r.output


@pytest.mark.story("CAP-042", "AC1")
@pytest.mark.parametrize("flag", ["--auto-approve", "--yes", "-y"])
def test_ci_ac1_flag_aliases(fake, run, environment, flag):
    r = run(flag, "bucket", "delete", "nova-dev-01", "orders")
    assert r.exit_code == 0, r.output
    assert [c.method for c in fake.writes()] == ["DELETE"]


@pytest.mark.story("CAP-042", "AC1")
def test_ci_ac1_env_var_is_not_approval(fake, run, environment):
    before = environment.read_text(encoding="utf-8")
    r = run("bucket", "delete", "nova-dev-01", "orders", extra_env={"CAPELLACTL_AUTO_APPROVE": "true"})
    assert r.exit_code == 1 and "refusing to delete a bucket without approval" in r.output
    assert fake.writes() == [] and environment.read_text(encoding="utf-8") == before


@pytest.mark.story("CAP-042", "AC2")
def test_ci_ac2_no_command_reads_stdin(fake, run, environment):
    """With empty stdin and no terminal, nothing reaches click's own prompt (which would answer 'Aborted!')."""
    commands = [args for args, _ in WRITE_COMMANDS] + [
        ["init"], ["configure"], ["import"], ["cluster", "update", "nova-dev-01"], ["bucket", "update", "nova-dev-01",
                                                                                     "orders"]]
    for args in commands:
        started = time.monotonic()
        r = run(*args, input="")
        assert time.monotonic() - started < 5, args
        assert "Aborted!" not in r.output, (args, r.output)
        assert r.exit_code in (0, 1, 3, 4), (args, r.exit_code, r.output)


@pytest.mark.story("CAP-042", "AC2")
def test_ci_ac2_missing_required_answer_exits_3(fake, run):
    r = run("configure", no_env=True, input="")
    assert r.exit_code == 3, r.output
    assert "[ERROR]: missing --api-key-stdin: there is no terminal to ask for it\n[ACTION]: Give it on the command line: --api-key-stdin VALUE." in r.output


@pytest.mark.story("CAP-042", "AC3")
@pytest.mark.parametrize("args,verb", WRITE_COMMANDS, ids=IDS)
def test_ci_ac3_uniform_refusal(fake, run, environment, args, verb):
    before = environment.read_text(encoding="utf-8")
    r = run(*args)
    assert r.exit_code == 1, r.output
    assert f"[ERROR]: refusing to {verb} without approval: there is no terminal to ask\n[ACTION]: Add --auto-approve" in r.output
    assert "pipeline step" not in r.output
    assert fake.writes() == [] and environment.read_text(encoding="utf-8") == before
    r = run(*args, extra_env={"CI": "true"})
    assert r.exit_code == 1 and "[ACTION]: Add --auto-approve to this pipeline step." in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-042", "AC4")
@pytest.mark.parametrize("quiet", [["--quiet"], ["-q"], "env"])
def test_ci_ac4_quiet_success_output(fake, run, environment, quiet):
    flags, env = (quiet, None) if quiet != "env" else ([], {"CAPELLACTL_QUIET": "true"})
    r = run(*flags, "--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "4", extra_env=env)
    assert r.exit_code == 0, r.output
    assert "Plan: 0 to add, 1 to change, 0 to delete, 0 blocked." in r.output
    for noisy in ("previous version kept", "→", "Apply complete", "Project nova-dev ·", "numOfNodes"):
        assert noisy not in r.output, noisy
    assert "nova-dev-01" in r.output  # the result table
    r = run(*flags, "--auto-approve", "-o", "json", "bucket", "update", "nova-dev-01", "orders", "--memory", "512",
            extra_env=env)
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["result"]["status"] == "ok"


@pytest.mark.story("CAP-042", "AC4")
def test_ci_ac4_quiet_still_shows_errors(fake, run, environment):
    r = run("--quiet", "cluster", "delete", "nova-dev-01")
    assert r.exit_code == 1 and "refusing to delete a cluster without approval" in r.output
    r = run("--quiet", "--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "2")
    assert r.exit_code == 3 and "between 3 and 27" in r.output
    fake.fail_next("PUT", "*/clusters/*", 422)
    r = run("--quiet", "--auto-approve", "cluster", "update", "nova-dev-01", "--description", "CI")
    assert r.exit_code == 1 and "Failed: cluster" in r.output


@pytest.mark.story("CAP-042", "AC5")
@pytest.mark.parametrize("args,prompt", [
    (["bucket", "delete", "nova-dev-01", "orders"], "Type the bucket name to confirm deletion"),
    (["cluster", "delete", "nova-dev-01"], "Type the cluster name to confirm deletion"),
    (["cidr", "delete", "nova-dev-01", "203.0.113.10/32"], "will be refused. Delete it?"),
    (["cluster", "update", "nova-dev-01", "--description", "CI"], "in capella.yaml and apply"),
    (["destroy"], "Type the project name to confirm"),
])
def test_ci_ac5_terminal_still_confirms(fake, run, environment, monkeypatch, args, prompt):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run(*args, input="no\n")
    assert prompt in r.output, r.output
    assert "refusing" not in r.output and fake.writes() == []


@pytest.mark.story("CAP-042", "AC7")
def test_ci_ac7_rerun_zero_writes(fake, run, write_config):
    from tests.conftest import MINIMAL

    write_config(MINIMAL)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0 and fake.writes() == []
    assert run("plan", "--detailed-exitcode").exit_code == 0
