"""CAP-016 AC8 and CAP-032 AC2 against the sandbox: 3 → 4 → 3 nodes (scale-in guards pass), then a re-run with no
writes."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-016", "AC8")
@pytest.mark.story("CAP-032", "AC2")
def test_integration_ac2_scaling(it, shared, tmp_path):
    cfg = tmp_path / "capella.yaml"
    shared.import_into(it, cfg)
    r = it.cli("cluster", "scale", shared.cluster, "--nodes", "4", cfg=cfg)
    assert r.exit_code == 0, r.output
    r = it.cli("cluster", "scale", shared.cluster, "--nodes", "3", cfg=cfg)
    assert r.exit_code == 0 and "checks:" in r.output, r.output
    r = it.cli("apply", cfg=cfg)
    assert "No changes" in r.output and r.writes == [], r.output
