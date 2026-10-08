"""CAP-016 AC1/AC2/AC5: the scale-in guard arithmetic (resources/scaling.py)."""
from __future__ import annotations

import pytest

from capellactl.engine.context import RunContext
from capellactl.resources import scaling


def _g(nodes, services=("data", "index", "query"), ram=16):
    return {"node": {"compute": {"cpu": 4, "ram": ram}}, "numOfNodes": nodes, "services": list(services)}


@pytest.fixture
def ctx(monkeypatch):
    stats = {"totalMemoryInMb": 20480, "freeMemoryInMb": 8192}
    buckets = [{"name": "orders", "replicas": 1}]
    monkeypatch.setattr(scaling.ep, "get_cluster_stats", lambda c, p, i: stats)
    monkeypatch.setattr(scaling.ep, "list_buckets", lambda c, p, i: buckets)
    c = RunContext(client=None)  # type: ignore[arg-type]
    c.stats = stats  # type: ignore[attr-defined]
    return c


@pytest.mark.story("CAP-016", "AC1")
def test_scale_in_guard_ac1_memory_math(ctx):
    blocked, checks = scaling.check(ctx, "p", "c", [_g(5)], [_g(4)])
    assert blocked == [] and checks == "checks: memory ok (12,288 / ~16,384 MB) · replicas ok (max 1, needs 2 data nodes)"


@pytest.mark.story("CAP-016", "AC2")
def test_scale_in_guard_ac2_boundary_equal_allowed(ctx):
    ctx.stats["freeMemoryInMb"] = 4096  # allocated 16,384 == projected 20,480 × 4/5
    blocked, checks = scaling.check(ctx, "p", "c", [_g(5)], [_g(4)])
    assert blocked == [] and "memory ok (16,384 / ~16,384 MB)" in str(checks)
    ctx.stats["freeMemoryInMb"] = 4095
    blocked, _ = scaling.check(ctx, "p", "c", [_g(5)], [_g(4)])
    assert blocked and "buckets allocate 16,385 MB" in blocked[0]


@pytest.mark.story("CAP-016", "AC5")
def test_scale_in_guard_ac5_no_data_left_whatever_flags(ctx):
    ctx.allow_service_removal = ctx.allow_service_group_removal = ctx.skip_capacity_check = True
    blocked, _ = scaling.check(ctx, "p", "c", [_g(3)], [_g(3, services=("index", "query"))])
    assert blocked == ["scale-in blocked: removing the last group that runs data"]
