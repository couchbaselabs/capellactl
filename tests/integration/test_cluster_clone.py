"""CAP-049 AC9 against the sandbox (nightly, CAP-032): clone a single-node cluster to another region with one
bucket, scope and collection, then delete the clone."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-049", "AC9")
def test_cluster_clone_ac9_integration(it, shared, tmp_path):
    cfg, project = tmp_path / "capella.yaml", shared.project
    shared.import_into(it, cfg)
    source, clone = "capellactl-it-clone-src", "capellactl-it-clone-dst"
    try:
        r = it.cli("cluster", "create", source, "--size", "dev", "--support-plan", "basic", "--region", "us-east-1",
                   "--project", project, cfg=cfg)
        assert r.exit_code == 0, r.output
        for args in (["bucket", "create", source, "demo", "--memory", "128"], ["scope", "create", source, "demo", "inv"],
                     ["collection", "create", source, "demo", "inv", "items"]):
            r = it.cli(*args, "--project", project, cfg=cfg)
            assert r.exit_code == 0, r.output
        r = it.cli("cluster", "clone", source, clone, "--region", "us-west-2", "--project", project, cfg=cfg)
        assert r.exit_code == 0, r.output
        r = it.cli("plan", "--detailed-exitcode", cfg=cfg, approve=False)
        assert r.exit_code == 0, r.output
    finally:
        for name in (clone, source):
            it.cli("cluster", "delete", name, "--project", project, cfg=cfg)
