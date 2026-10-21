"""CAP-027 AC8 against the sandbox (nightly, CAP-032): create a credential, then connect with it through the SDK."""
from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.integration

PASSWORD = "Capellactl!It-Passw0rd"  # also a canary for the log scan (test_redaction_ci.py)


@pytest.mark.story("CAP-027", "AC8")
def test_credential_ac8_integration_connect(it, shared, tmp_path):
    if it.kind == "fake":
        pytest.skip("connecting with the SDK needs a real cluster")
    if not os.environ.get("CAPELLA_SANDBOX_CLIENT_CIDR"):
        pytest.skip("needs CAPELLA_SANDBOX_CLIENT_CIDR: this machine's address, allowed on the shared cluster")
    couchbase = pytest.importorskip("couchbase.cluster", reason="needs the Couchbase Python SDK")
    from couchbase.auth import PasswordAuthenticator
    from couchbase.options import ClusterOptions

    cfg, cluster, bucket, name = tmp_path / "capella.yaml", shared.cluster, shared.bucket, "capellactl_it_app"
    env = {"IT_CRED_PASSWORD": PASSWORD}
    shared.import_into(it, cfg, cluster=True)
    try:
        r = it.cli("credential", "create", cluster, name, "--privileges", "read+write", "--bucket", bucket,
                   "--password-env", "IT_CRED_PASSWORD", cfg=cfg, extra_env=env)
        assert r.exit_code == 0, r.output
        r = it.cli("plan", "--detailed-exitcode", cfg=cfg, approve=False, extra_env=env)
        assert r.exit_code == 0, r.output  # re-run: nothing to change, password not re-sent
        r = it.cli("-o", "json", "cluster", "get", cluster, cfg=cfg, approve=False, debug=False)
        conn = json.loads(r.output)["connectionString"]
        c = couchbase.Cluster(conn, ClusterOptions(PasswordAuthenticator(name, PASSWORD)))
        c.bucket(bucket).default_collection().exists("capellactl-it-probe")
    finally:
        it.cli("credential", "delete", cluster, name, cfg=cfg)
