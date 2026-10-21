"""CAP-020 AC9 and CAP-032 AC2 against the sandbox: create → re-run → update → pause → resume → delete."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-020", "AC9")
@pytest.mark.story("CAP-032", "AC2")
def test_integration_ac2_schedule(it, shared, tmp_path):
    cfg, cluster = tmp_path / "capella.yaml", shared.cluster
    shared.import_into(it, cfg)
    try:
        # always on, so the schedule never turns the shared cluster off during the run
        r = it.cli("cluster", "schedule", "set", cluster, "--timezone", "US/Pacific", "--weekdays", "00:00-24:00",
                   "--weekend", "on", cfg=cfg)
        assert r.exit_code == 0, r.output
        r = it.cli("apply", cfg=cfg)
        assert "No changes" in r.output and r.writes == [], r.output
        r = it.cli("cluster", "schedule", "set", cluster, "--sunday", "08:00-20:00", cfg=cfg)
        assert r.exit_code == 0 and "sunday" in r.output, r.output
        r = it.cli("cluster", "schedule", "pause", cluster, cfg=cfg)
        assert r.exit_code == 0, r.output
        r = it.cli("cluster", "schedule", "resume", cluster, cfg=cfg)
        assert r.exit_code == 0, r.output
    finally:
        r = it.cli("cluster", "schedule", "delete", cluster, cfg=cfg)
        assert r.exit_code == 0, r.output
