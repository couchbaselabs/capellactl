"""CAP-049 AC9 against a real sandbox organization (nightly, CAP-032): clone a single-node cluster to another
region with one bucket, scope and collection, then delete the clone."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-049", "AC9")
def test_cluster_clone_ac9_integration(tmp_path):
    needed = ("CAPELLA_SANDBOX_API_KEY", "CAPELLA_SANDBOX_ORG_ID", "CAPELLA_SANDBOX_PROJECT")
    if not all(os.environ.get(v) for v in needed):
        pytest.skip("needs " + ", ".join(needed))
    from click.testing import CliRunner

    from capellactl.cli.main import cli

    cfg = tmp_path / "capella.yaml"
    env = {"CAPELLA_API_KEY": os.environ["CAPELLA_SANDBOX_API_KEY"], "CAPELLA_ORG_ID": os.environ["CAPELLA_SANDBOX_ORG_ID"]}
    project = os.environ["CAPELLA_SANDBOX_PROJECT"]
    runner = CliRunner()
    r = runner.invoke(cli, ["import", "--project", project, "--file", str(cfg)], env=env)
    assert r.exit_code == 0, r.output
    source, clone = "capellactl-it-clone-src", "capellactl-it-clone-dst"
    base = ["-c", str(cfg), "--auto-approve"]
    try:
        r = runner.invoke(cli, [*base, "cluster", "create", source, "--size", "dev", "--support-plan", "basic",
                                "--region", "us-east-1", "--project", project], env=env)
        assert r.exit_code == 0, r.output
        for args in (["bucket", "create", source, "demo", "--memory", "128"], ["scope", "create", source, "demo", "inv"],
                     ["collection", "create", source, "demo", "inv", "items"]):
            r = runner.invoke(cli, [*base, *args, "--project", project], env=env)
            assert r.exit_code == 0, r.output
        r = runner.invoke(cli, [*base, "cluster", "clone", source, clone, "--region", "us-west-2", "--project", project],
                          env=env)
        assert r.exit_code == 0, r.output
        r = runner.invoke(cli, ["-c", str(cfg), "plan", "--detailed-exitcode"], env=env)
        assert r.exit_code == 0, r.output
    finally:
        for name in (clone, source):
            runner.invoke(cli, [*base, "cluster", "delete", name, "--project", project], env=env)
