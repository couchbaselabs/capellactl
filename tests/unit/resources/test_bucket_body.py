"""CAP-023 AC3: the bucket PUT body is observed state overlaid with desired state."""
from __future__ import annotations

import pytest

from capellactl.resources.bucket import bucket_changes, build_update_body, create_summary


@pytest.mark.story("CAP-023", "AC3")
def test_bucket_body_ac3_overlay():
    observed = {"id": "b3JkZXJz", "name": "orders", "type": "couchbase", "memoryAllocationInMb": 1024,
                "durabilityLevel": "majority", "replicas": 2, "timeToLiveInSeconds": 600, "flush": True,
                "priority": 4, "stats": {"itemCount": 3}}
    body = build_update_body(observed, {"name": "orders", "memoryAllocationInMb": 2048, "type": "couchbase"})
    assert body == {"memoryAllocationInMb": 2048, "durabilityLevel": "majority", "replicas": 2,
                    "timeToLiveInSeconds": 600, "flushEnabled": True, "priority": 4}


@pytest.mark.story("CAP-023", "AC3")
def test_bucket_body_ac3_flush_enabled_wins_over_deprecated_flush():
    immutable, changes = bucket_changes({"flushEnabled": False}, {"flushEnabled": False, "flush": True})
    assert immutable == [] and changes == []


@pytest.mark.story("CAP-023", "AC1")
def test_bucket_summary_ac1():
    assert create_summary({"type": "couchbase", "storageBackend": "magma", "memoryAllocationInMb": 1024,
                           "replicas": 1, "durabilityLevel": "majority"}) == \
        "couchbase · magma · 1024 MB · 1 replica · durability majority"
    assert create_summary({"type": "ephemeral", "memoryAllocationInMb": 256, "replicas": 2}) == \
        "ephemeral · 256 MB · 2 replicas"
