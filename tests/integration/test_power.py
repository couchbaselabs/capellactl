"""CAP-019 AC8 and CAP-032 AC2 against the sandbox: off → off again (nothing to do) → on."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.story("CAP-019", "AC8")
@pytest.mark.story("CAP-032", "AC2")
def test_integration_ac2_power(it, shared, tmp_path):
    cfg = tmp_path / "capella.yaml"
    shared.import_into(it, cfg)
    try:
        r = it.cli("cluster", "power", shared.cluster, "--off", cfg=cfg)
        assert r.exit_code == 0 and "is off" in r.output, r.output
        r = it.cli("cluster", "power", shared.cluster, "--off", cfg=cfg)
        assert r.exit_code == 0 and "already off" in r.output and r.writes == [], r.output
    finally:
        r = it.cli("cluster", "power", shared.cluster, "--on", cfg=cfg)
        assert r.exit_code == 0, r.output
