"""CAP-023 AC5: offline bucket type rules (validate exits 3)."""
from __future__ import annotations

import pytest

from capellactl.config.crossref import bucket_type_rules
from tests.conftest import MINIMAL


@pytest.mark.story("CAP-023", "AC5")
@pytest.mark.parametrize(("bucket", "field", "message"), [
    ({"type": "ephemeral", "storageBackend": "magma"}, "storageBackend", "not allowed for ephemeral buckets"),
    ({"type": "ephemeral", "evictionPolicy": "fullEviction"}, "evictionPolicy",
     "fullEviction is not valid for ephemeral buckets"),
    ({"type": "couchbase", "evictionPolicy": "nruEviction"}, "evictionPolicy",
     "nruEviction is only valid for ephemeral buckets"),
    ({"type": "ephemeral", "durabilityLevel": "persistToMajority"}, "durabilityLevel",
     "persistToMajority needs disk persistence"),
    ({"type": "couchbase", "storageBackend": "couchstore", "vbuckets": 128}, "vbuckets",
     "only allowed with storageBackend: magma"),
])
def test_bucket_validate_ac5_type_rules(bucket, field, message):
    issues = bucket_type_rules({"name": "b", **bucket})
    assert [f for f, _ in issues] == [field]
    assert message in issues[0][1]


@pytest.mark.story("CAP-023", "AC5")
def test_bucket_validate_ac5_valid_buckets_pass():
    assert bucket_type_rules({"type": "ephemeral", "evictionPolicy": "nruEviction", "durabilityLevel": "majority"}) == []
    assert bucket_type_rules({"type": "couchbase", "storageBackend": "magma", "vbuckets": 128,
                              "evictionPolicy": "fullEviction", "durabilityLevel": "persistToMajority"}) == []


@pytest.mark.story("CAP-023", "AC5")
def test_bucket_validate_ac5_validate_exits_3(run, write_config):
    write_config(MINIMAL + "    buckets:\n      - name: sessions\n        type: ephemeral\n"
                           "        storageBackend: magma\n        memoryAllocationInMb: 256\n")
    r = run("validate")
    assert r.exit_code == 3
    assert "clusters[0].buckets[0].storageBackend: not allowed for ephemeral buckets" in r.output
