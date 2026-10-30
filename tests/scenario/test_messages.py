"""CAP-063: warnings, config problems and usage errors in the [ERROR]/[WARNING] + [ACTION] form."""
from __future__ import annotations

import pytest
from freezegun import freeze_time

from tests.conftest import MINIMAL, seed_healthy
from tests.scenario.test_sync import _seed_bucket_and_credential, imported  # noqa: F401


def _no_old_labels(output: str) -> None:
    for line in output.splitlines():
        assert not line.startswith(("warning:", "Error:", "Hint:", "See:")), line


@pytest.mark.story("CAP-063", "AC3")
def test_messages_ac3_warnings(fake, run, write_config, imported):  # noqa: F811
    # settings: a deprecated variable
    r = run("validate", no_env=True, extra_env={"BEARER_TOKEN": "legacy-token-0123456789", "CAPELLA_ORG_ID": "org-1"})
    assert "[WARNING]: BEARER_TOKEN is deprecated\n[ACTION]: Set CAPELLA_API_KEY instead" in r.output, r.output
    _no_old_labels(r.output)

    # sync: a turned-off cluster's buckets and credentials are kept from the file
    cid = _seed_bucket_and_credential(fake)
    assert run("sync").exit_code == 0
    fake.set_transition(cid, ["turnedOff"])
    r = run("sync")
    assert r.exit_code == 0, r.output
    assert ("[WARNING]: cluster nova-dev-01: buckets, scopes and collections, database credentials kept from "
            "capella.yaml (turnedOff)\n[ACTION]: Run 'capellactl sync' again when the cluster is on") in r.output
    _no_old_labels(r.output)

    # config: an allowed IP range that has expired
    write_config(MINIMAL + "    allowedCidrs:\n      - cidr: 198.51.100.0/24\n        expiresAt: \"2026-01-01T00:00:00Z\"\n")
    with freeze_time("2026-10-05T17:00:00Z"):
        r = run("validate")
    assert r.exit_code == 0, r.output
    assert "expiresAt is in the past, so Capella will remove this IP range\n[ACTION]: Run 'capellactl cidr delete " \
           "nova-dev-01 198.51.100.0/24'" in r.output
    _no_old_labels(r.output)


@pytest.mark.story("CAP-063", "AC6")
def test_messages_ac6_config_warnings_only_where_relevant(fake, run, write_config):
    """validate lists config warnings, plan and apply count them in one line, other commands print none."""
    seed_healthy(fake)
    write_config(MINIMAL + "    allowedCidrs:\n      - cidr: 198.51.100.0/24\n        expiresAt: \"2026-01-01T00:00:00Z\"\n"
                           "    databaseCredentials:\n      - name: ops_ro\n        access:\n          - privileges: [read]\n")
    with freeze_time("2026-10-05T17:00:00Z"):
        v, p, c = run("validate"), run("plan"), run("cidr", "list", "nova-dev-01")
    assert v.output.count("[WARNING]:") == 2, v.output
    assert p.output.count("[WARNING]:") == 1, p.output
    assert ("[WARNING]: capella.yaml has 2 settings that may not be intended\n"
            "[ACTION]: Run 'capellactl validate' to see them.") in p.output
    assert c.exit_code == 0 and "[WARNING]" not in c.output, c.output


@pytest.mark.story("CAP-063", "AC4")
def test_messages_ac4_config_problems(fake, run, write_config):
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 2"))
    r = run("validate")
    assert r.exit_code == 3
    assert r.output.splitlines() == [
        "[ERROR]: capella.yaml has 1 problem:",
        "  project nova-dev › cluster nova-dev-01 › service group data,index,query › numOfNodes (line 16)",
        "    must be between 3 and 27",
        "[ACTION]: Fix each problem above (an 'action:' line says how), then run the command again. "
        "See 'capellactl help scaling'.",
    ]


@pytest.mark.story("CAP-063", "AC5")
@pytest.mark.parametrize("args,error,action", [
    (["cluster", "create", "x", "--nope"], "[ERROR]: No such option '--nope'",
     "[ACTION]: Run 'capellactl cluster create --help' to see its commands, options and examples."),
    (["clustr"], "[ERROR]: unknown command 'clustr'. Did you mean 'cluster'?",
     "[ACTION]: Run 'capellactl --help' to see its commands, options and examples."),
    (["cluster", "create"], "[ERROR]: Missing argument 'NAME'.",
     "[ACTION]: Run 'capellactl cluster create --help'"),
])
def test_messages_ac5_usage_errors(run, args, error, action):
    r = run(*args)
    assert r.exit_code == 2, r.output
    assert error in r.output and action in r.output, r.output
    assert r.output.startswith("Usage: ")
    _no_old_labels(r.output)
