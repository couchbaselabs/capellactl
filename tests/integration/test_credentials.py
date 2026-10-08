"""CAP-027 AC8 against a real sandbox organization (nightly, CAP-032)."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-027", "AC8")
def test_credential_ac8_integration_connect(tmp_path):
    needed = ("CAPELLA_SANDBOX_API_KEY", "CAPELLA_SANDBOX_ORG_ID", "CAPELLA_SANDBOX_PROJECT", "CAPELLA_SANDBOX_CLUSTER",
              "CAPELLA_SANDBOX_BUCKET")
    if not all(os.environ.get(v) for v in needed):
        pytest.skip("needs " + ", ".join(needed))
    couchbase = pytest.importorskip("couchbase.cluster", reason="needs the Couchbase Python SDK")
    from click.testing import CliRunner

    from capellactl.cli.main import cli

    cfg = tmp_path / "capella.yaml"
    env = {"CAPELLA_API_KEY": os.environ["CAPELLA_SANDBOX_API_KEY"], "CAPELLA_ORG_ID": os.environ["CAPELLA_SANDBOX_ORG_ID"],
           "IT_CRED_PASSWORD": "Capellactl!It-Passw0rd"}
    runner = CliRunner()
    cluster, bucket = os.environ["CAPELLA_SANDBOX_CLUSTER"], os.environ["CAPELLA_SANDBOX_BUCKET"]
    r = runner.invoke(cli, ["import", "--project", os.environ["CAPELLA_SANDBOX_PROJECT"], "--cluster", cluster,
                            "--file", str(cfg)], env=env)
    assert r.exit_code == 0, r.output
    name = "capellactl_it_app"
    base = ["-c", str(cfg), "--auto-approve"]
    try:
        r = runner.invoke(cli, [*base, "credential", "create", cluster, name, "--privileges", "read+write", "--bucket",
                                bucket, "--password-env", "IT_CRED_PASSWORD"], env=env)
        assert r.exit_code == 0, r.output
        r = runner.invoke(cli, ["-c", str(cfg), "plan", "--detailed-exitcode"], env=env)
        assert r.exit_code == 0, r.output  # re-run: nothing to change, password not re-sent
        r = runner.invoke(cli, ["-c", str(cfg), "-o", "json", "cluster", "get", cluster], env=env)
        conn = __import__("json").loads(r.output)["connectionString"]
        from couchbase.auth import PasswordAuthenticator
        from couchbase.options import ClusterOptions

        c = couchbase.Cluster(conn, ClusterOptions(PasswordAuthenticator(name, env["IT_CRED_PASSWORD"])))
        c.bucket(bucket).default_collection().exists("capellactl-it-probe")
    finally:
        runner.invoke(cli, [*base, "credential", "delete", cluster, name], env=env)
