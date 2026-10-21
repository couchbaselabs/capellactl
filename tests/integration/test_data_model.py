"""CAP-023 AC8 and CAP-025 AC8 against the sandbox (nightly, CAP-032)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-023", "AC8")
def test_bucket_ac8_integration(it, shared, tmp_path):
    cfg, cluster, name = tmp_path / "capella.yaml", shared.cluster, "capellactl-it-bucket"
    shared.import_into(it, cfg, cluster=True)
    try:
        r = it.cli("bucket", "create", cluster, name, "--memory", "100", cfg=cfg)
        assert r.exit_code == 0, r.output
        r = it.cli("plan", "--detailed-exitcode", cfg=cfg, approve=False)
        assert r.exit_code == 0, r.output  # re-run: nothing to change
    finally:
        it.cli("bucket", "delete", cluster, name, cfg=cfg)


@pytest.mark.story("CAP-025", "AC8")
def test_scopes_ac8_integration(it, shared, tmp_path):
    cfg, cluster, bucket = tmp_path / "capella.yaml", shared.cluster, "capellactl-it-scopes"
    shared.import_into(it, cfg, cluster=True)
    try:
        for args in (["bucket", "create", cluster, bucket, "--memory", "100"],
                     ["scope", "create", cluster, bucket, "inventory"],
                     ["collection", "create", cluster, bucket, "inventory", "items"],
                     ["collection", "create", cluster, bucket, "inventory", "suppliers", "--max-ttl", "-1"]):
            r = it.cli(*args, cfg=cfg)
            assert r.exit_code == 0, r.output
        r = it.cli("plan", "--detailed-exitcode", cfg=cfg, approve=False)
        assert r.exit_code == 0, r.output  # re-run: nothing to change
        r = it.cli("collection", "delete", cluster, bucket, "inventory", "items", cfg=cfg)
        assert r.exit_code == 0, r.output
        r = it.cli("scope", "delete", cluster, bucket, "inventory", cfg=cfg)
        assert r.exit_code == 0, r.output
    finally:
        it.cli("bucket", "delete", cluster, bucket, cfg=cfg)
