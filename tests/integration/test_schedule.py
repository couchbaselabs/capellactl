"""CAP-020 AC9 against a real sandbox organization (nightly, CAP-032): create → re-run → update → delete."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-020", "AC9")
def test_schedule_ac9_integration(tmp_path):
    needed = ("CAPELLA_SANDBOX_API_KEY", "CAPELLA_SANDBOX_ORG_ID", "CAPELLA_SANDBOX_PROJECT", "CAPELLA_SANDBOX_CLUSTER")
    if not all(os.environ.get(v) for v in needed):
        pytest.skip("needs " + ", ".join(needed))
    from click.testing import CliRunner

    from capellactl.cli.main import cli

    cfg, cluster = tmp_path / "capella.yaml", os.environ["CAPELLA_SANDBOX_CLUSTER"]
    env = {"CAPELLA_API_KEY": os.environ["CAPELLA_SANDBOX_API_KEY"], "CAPELLA_ORG_ID": os.environ["CAPELLA_SANDBOX_ORG_ID"]}
    runner = CliRunner()
    assert runner.invoke(cli, ["import", "--project", os.environ["CAPELLA_SANDBOX_PROJECT"], "--file", str(cfg)],
                         env=env).exit_code == 0
    base = ["-c", str(cfg), "--auto-approve"]
    try:
        r = runner.invoke(cli, [*base, "cluster", "schedule", "set", cluster, "--timezone", "US/Pacific",
                                "--weekdays", "00:00-24:00", "--weekend", "on"], env=env)
        assert r.exit_code == 0, r.output
        r = runner.invoke(cli, [*base, "apply"], env=env)
        assert "No changes" in r.output, r.output
        r = runner.invoke(cli, [*base, "cluster", "schedule", "set", cluster, "--sunday", "08:00-20:00"], env=env)
        assert r.exit_code == 0 and "sunday" in r.output, r.output
    finally:
        r = runner.invoke(cli, [*base, "cluster", "schedule", "delete", cluster], env=env)
        assert r.exit_code == 0, r.output
