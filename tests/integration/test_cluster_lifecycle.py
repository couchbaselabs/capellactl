"""CAP-014 AC7 against the sandbox (nightly, CAP-032): deploy, protect, delete, re-run."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-014", "AC7")
def test_cluster_delete_ac7_integration(it, shared, tmp_path):
    cfg, name = tmp_path / "capella.yaml", "capellactl-it-lifecycle"
    shared.import_into(it, cfg)
    try:
        r = it.cli("cluster", "create", name, "--size", "dev", "--support-plan", "basic", "--project", shared.project,
                   cfg=cfg)
        assert r.exit_code == 0, r.output
        r = it.cli("cluster", "protect", name, "--on", cfg=cfg)
        assert r.exit_code == 0, r.output
        r = it.cli("cluster", "delete", name, cfg=cfg)
        assert r.exit_code == 4, r.output  # protected
        assert it.cli("cluster", "protect", name, "--off", cfg=cfg).exit_code == 0
        r = it.cli("cluster", "delete", name, cfg=cfg)
        assert r.exit_code == 0 and f"deleted cluster {name}" in r.output, r.output
        r = it.cli("cluster", "delete", name, cfg=cfg)
        assert r.exit_code == 0 and "not found, nothing to do" in r.output, r.output
        assert r.writes == [], r.writes  # re-run: zero writes
    finally:
        it.cli("cluster", "protect", name, "--off", cfg=cfg)
        it.cli("cluster", "delete", name, cfg=cfg)
