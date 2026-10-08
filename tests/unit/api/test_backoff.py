"""CAP-003 AC3: backoff."""
from __future__ import annotations

import random

import pytest

from capellactl.api.client import backoff_delay


@pytest.mark.story("CAP-003", "AC3")
def test_client_ac3_backoff_capped_at_30s():
    rng = random.Random(42)
    for attempt in range(1, 20):
        d = backoff_delay(attempt, rng)
        assert 0 <= d <= min(30, 2 ** (attempt - 1))
