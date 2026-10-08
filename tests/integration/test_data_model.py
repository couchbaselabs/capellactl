"""CAP-023 AC8 against a real sandbox organization (nightly, CAP-032)."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-023", "AC8")
def test_bucket_ac8_integration(tmp_path):
    needed = ("CAPELLA_SANDBOX_API_KEY", "CAPELLA_SANDBOX_ORG_ID", "CAPELLA_SANDBOX_PROJECT", "CAPELLA_SANDBOX_CLUSTER")
    if not all(os.environ.get(v) for v in needed):
        pytest.skip("needs " + ", ".join(needed))
    from click.testing import CliRunner

    from capellactl.cli.main import cli

    cfg = tmp_path / "capella.yaml"
    env = {"CAPELLA_API_KEY": os.environ["CAPELLA_SANDBOX_API_KEY"], "CAPELLA_ORG_ID": os.environ["CAPELLA_SANDBOX_ORG_ID"]}
    runner = CliRunner()
    r = runner.invoke(cli, ["import", "--project", os.environ["CAPELLA_SANDBOX_PROJECT"], "--cluster",
                            os.environ["CAPELLA_SANDBOX_CLUSTER"], "--file", str(cfg)], env=env)
    assert r.exit_code == 0, r.output
    name = "capellactl-it-bucket"
    base = ["-c", str(cfg), "--auto-approve"]
    cluster = os.environ["CAPELLA_SANDBOX_CLUSTER"]
    try:
        r = runner.invoke(cli, [*base, "bucket", "create", cluster, name, "--memory", "100"], env=env)
        assert r.exit_code == 0, r.output
        r = runner.invoke(cli, ["-c", str(cfg), "plan", "--detailed-exitcode"], env=env)
        assert r.exit_code == 0, r.output  # re-run: nothing to change
    finally:
        runner.invoke(cli, [*base, "bucket", "delete", cluster, name], env=env)


@pytest.mark.story("CAP-025", "AC8")
def test_scopes_ac8_integration(tmp_path):
    needed = ("CAPELLA_SANDBOX_API_KEY", "CAPELLA_SANDBOX_ORG_ID", "CAPELLA_SANDBOX_PROJECT", "CAPELLA_SANDBOX_CLUSTER")
    if not all(os.environ.get(v) for v in needed):
        pytest.skip("needs " + ", ".join(needed))
    from click.testing import CliRunner

    from capellactl.cli.main import cli

    cfg = tmp_path / "capella.yaml"
    env = {"CAPELLA_API_KEY": os.environ["CAPELLA_SANDBOX_API_KEY"], "CAPELLA_ORG_ID": os.environ["CAPELLA_SANDBOX_ORG_ID"]}
    runner = CliRunner()
    r = runner.invoke(cli, ["import", "--project", os.environ["CAPELLA_SANDBOX_PROJECT"], "--cluster",
                            os.environ["CAPELLA_SANDBOX_CLUSTER"], "--file", str(cfg)], env=env)
    assert r.exit_code == 0, r.output
    bucket = "capellactl-it-scopes"
    base = ["-c", str(cfg), "--auto-approve"]
    cluster = os.environ["CAPELLA_SANDBOX_CLUSTER"]
    try:
        for args in (["bucket", "create", cluster, bucket, "--memory", "100"],
                     ["scope", "create", cluster, bucket, "inventory"],
                     ["collection", "create", cluster, bucket, "inventory", "items"],
                     ["collection", "create", cluster, bucket, "inventory", "suppliers", "--max-ttl", "-1"]):
            r = runner.invoke(cli, [*base, *args], env=env)
            assert r.exit_code == 0, r.output
        r = runner.invoke(cli, ["-c", str(cfg), "plan", "--detailed-exitcode"], env=env)
        assert r.exit_code == 0, r.output  # re-run: nothing to change
        r = runner.invoke(cli, [*base, "collection", "delete", cluster, bucket, "inventory", "items"], env=env)
        assert r.exit_code == 0, r.output
        r = runner.invoke(cli, [*base, "scope", "delete", cluster, bucket, "inventory"], env=env)
        assert r.exit_code == 0, r.output
    finally:
        runner.invoke(cli, [*base, "bucket", "delete", cluster, bucket], env=env)
