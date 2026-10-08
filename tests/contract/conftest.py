from __future__ import annotations

import random
from collections.abc import Iterator

import pytest
import responses

from capellactl import DEFAULT_BASE_URL
from capellactl.api.client import CapellaClient
from capellactl.engine.clock import FakeClock

BASE = DEFAULT_BASE_URL
KEY = "contract-key-abcdef123456"


@pytest.fixture
def rsps() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock() as r:
        yield r


@pytest.fixture
def fclock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(fclock: FakeClock) -> CapellaClient:
    return CapellaClient(KEY, "org-1", BASE, clock=fclock, rng=random.Random(7))
