"""CAP-014 AC7 against a real sandbox organization (nightly, CAP-032): deploy, protect, delete, re-run."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-014", "AC7")
def test_cluster_delete_ac7_integration(tmp_path):
    needed = ("CAPELLA_SANDBOX_API_KEY", "CAPELLA_SANDBOX_ORG_ID", "CAPELLA_SANDBOX_PROJECT")
    if not all(os.environ.get(v) for v in needed):
        pytest.skip("needs " + ", ".join(needed))
    from click.testing import CliRunner

    from capellactl.cli.main import cli

    cfg = tmp_path / "capella.yaml"
    env = {"CAPELLA_API_KEY": os.environ["CAPELLA_SANDBOX_API_KEY"], "CAPELLA_ORG_ID": os.environ["CAPELLA_SANDBOX_ORG_ID"]}
    runner = CliRunner()
    r = runner.invoke(cli, ["import", "--project", os.environ["CAPELLA_SANDBOX_PROJECT"], "--file", str(cfg)], env=env)
    assert r.exit_code == 0, r.output
    name = "capellactl-it-lifecycle"
    base = ["-c", str(cfg), "--auto-approve"]
    try:
        r = runner.invoke(cli, [*base, "cluster", "create", name, "--size", "dev", "--support-plan", "basic",
                                "--project", os.environ["CAPELLA_SANDBOX_PROJECT"]], env=env)
        assert r.exit_code == 0, r.output
        r = runner.invoke(cli, [*base, "cluster", "protect", name, "--on"], env=env)
        assert r.exit_code == 0, r.output
        r = runner.invoke(cli, [*base, "cluster", "delete", name], env=env)
        assert r.exit_code == 4, r.output  # protected
        assert runner.invoke(cli, [*base, "cluster", "protect", name, "--off"], env=env).exit_code == 0
        r = runner.invoke(cli, [*base, "cluster", "delete", name], env=env)
        assert r.exit_code == 0 and f"deleted cluster {name}" in r.output, r.output
        r = runner.invoke(cli, [*base, "cluster", "delete", name], env=env)
        assert r.exit_code == 0 and "not found, nothing to do" in r.output, r.output  # re-run: zero writes
    finally:
        runner.invoke(cli, [*base, "cluster", "protect", name, "--off"], env=env)
        runner.invoke(cli, [*base, "cluster", "delete", name], env=env)
