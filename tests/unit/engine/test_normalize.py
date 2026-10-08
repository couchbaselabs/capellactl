"""CAP-005 AC3, AC4: comparison rules."""
from __future__ import annotations

import pytest

from capellactl.config.loader import apply_defaults
from capellactl.engine.normalize import canon_flush, field_changes
from capellactl.resources.cluster import ClusterReconciler

G1 = {"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
      "numOfNodes": 3, "services": ["data", "index", "query"]}
G2 = {"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
      "numOfNodes": 2, "services": ["search"]}


def _bucket(**kw):
    data = {"clusters": [{"buckets": [{"name": "b", "memoryAllocationInMb": 100, **kw}]}]}
    apply_defaults(data)
    return data["clusters"][0]["buckets"][0]


@pytest.mark.story("CAP-005", "AC3")
def test_normalize_ac3_undeclared_field_ignored():
    observed = {"name": "b", "memoryAllocationInMb": 100, "priority": 5, "replicas": 1, "type": "couchbase",
                "durabilityLevel": "none", "timeToLiveInSeconds": 0, "flushEnabled": False,
                "bucketConflictResolution": "seqno"}
    assert field_changes(_bucket(), observed) == []


@pytest.mark.story("CAP-005", "AC3")
def test_normalize_ac3_default_compared():
    observed = {"name": "b", "memoryAllocationInMb": 100, "replicas": 2}
    changes = field_changes({k: v for k, v in _bucket().items() if k in ("name", "memoryAllocationInMb", "replicas")},
                            observed)
    assert [(c.path, c.before, c.after) for c in changes] == [("replicas", 2, 1)]


def _cluster(groups, plan="developer pro"):
    return {"name": "c", "support": {"plan": plan}, "serviceGroups": groups}


@pytest.mark.story("CAP-005", "AC4")
@pytest.mark.parametrize("desired,observed", [
    (_cluster([{**G1, "services": ["query", "data", "index"]}]), _cluster([G1])),
    (_cluster([G2, G1]), _cluster([G1, G2])),
    (_cluster([G1], plan="Developer Pro"), _cluster([G1], plan="developer pro")),
])
def test_normalize_ac4_equivalences(desired, observed):
    _, changes, blocked, _ = ClusterReconciler()._changes(desired, observed)
    assert changes == [] and blocked == []


@pytest.mark.story("CAP-005", "AC4")
def test_normalize_ac4_privilege_aliases():
    d = {"access": {"privileges": ["read", "write"]}}
    o = {"access": {"privileges": ["data_writer", "data_reader"]}}
    assert field_changes(d, o) == []


@pytest.mark.story("CAP-005", "AC4")
def test_normalize_ac4_flush_fallback():
    assert canon_flush({"flush": False}) is False
    assert canon_flush({"flush": True, "flushEnabled": False}) is False
