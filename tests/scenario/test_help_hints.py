"""CAP-034 AC5: errors point to help topics."""
from __future__ import annotations

import pytest

from tests.conftest import MINIMAL, seed_healthy


@pytest.mark.story("CAP-034", "AC5")
def test_help_ac5_blocked_reason_has_topic(fake, run, write_config):
    _, cid = seed_healthy(fake, nodes=5)
    fake.seed_bucket(cid, "orders", replicas=3)
    write_config(MINIMAL)  # 5 → 3 data nodes: bucket orders' 3 replicas need 4, so the scale-in is blocked
    r = run("plan")
    assert r.exit_code == 4
    assert "See: capellactl help scaling" in r.output
    write_config(MINIMAL.replace("us-east-1", "us-west-2"))
    r = run("plan")
    assert "See: capellactl help idempotency" in r.output


@pytest.mark.story("CAP-034", "AC5")
def test_help_ac5_validation_error_has_topic(run, write_config):
    write_config(MINIMAL + "    hibernation:\n      timezone: US/Pacific\n      weekend: sometimes\n")
    r = run("validate")
    assert r.exit_code == 3
    assert "See: capellactl help hibernation" in r.output
