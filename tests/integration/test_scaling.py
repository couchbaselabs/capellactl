"""CAP-016 AC8 against a real sandbox organization (nightly, CAP-032): 4 → 3 nodes, then a re-run with no writes."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-016", "AC8")
def test_scale_in_ac8_integration(tmp_path):
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
    r = runner.invoke(cli, [*base, "cluster", "scale", cluster, "--nodes", "4"], env=env)
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli, [*base, "cluster", "scale", cluster, "--nodes", "3"], env=env)
    assert r.exit_code == 0 and "checks:" in r.output, r.output
    r = runner.invoke(cli, [*base, "apply"], env=env)
    assert "No changes" in r.output, r.output
