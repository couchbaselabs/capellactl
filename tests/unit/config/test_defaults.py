"""CAP-002 AC5: defaults applied."""
from __future__ import annotations

import pytest

from capellactl.config.loader import load_config
from tests.conftest import MINIMAL


@pytest.mark.story("CAP-002", "AC5")
def test_loader_ac5_bucket_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL + "    buckets:\n      - name: orders\n        memoryAllocationInMb: 1024\n", encoding="utf-8")
    b = load_config(p, env={"CAPELLA_ORG_ID": "o"}).clusters[0]["buckets"][0]
    assert {k: b[k] for k in ("type", "replicas", "durabilityLevel", "timeToLiveInSeconds", "flushEnabled",
                              "bucketConflictResolution")} == {
        "type": "couchbase", "replicas": 1, "durabilityLevel": "none", "timeToLiveInSeconds": 0,
        "flushEnabled": False, "bucketConflictResolution": "seqno"}
    assert "priority" not in b  # depends on server version; never defaulted (CAP-005 AC3)


@pytest.mark.story("CAP-002", "AC5")
def test_loader_ac5_cluster_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL, encoding="utf-8")
    assert load_config(p, env={"CAPELLA_ORG_ID": "o"}).clusters[0]["configurationType"] == "multiNode"
