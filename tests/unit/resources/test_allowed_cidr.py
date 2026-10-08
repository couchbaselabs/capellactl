"""CAP-022: allowed-CIDR normalisation and comparison."""
from __future__ import annotations

import pytest

from capellactl.resources.allowed_cidr import AllowedCidrReconciler, canonical, cidr_changes, create_body
from capellactl.resources.base import Observed


@pytest.mark.story("CAP-022", "AC2")
def test_cidr_normalize_ac2_bare_ip_is_32():
    assert canonical("203.0.113.10") == "203.0.113.10/32"
    assert canonical(" 2001:db8::1 ") == "2001:db8::1/128"
    rec = AllowedCidrReconciler()
    obs = [Observed("a", {"cidr": "203.0.113.10/32"}), Observed("b", {"cidr": "198.51.100.0/24"})]
    assert [o.id for o in rec.match({"cidr": "203.0.113.10"}, obs)] == ["a"]
    assert rec.key({"cidr": "203.0.113.10"}, None) == "203.0.113.10/32"


@pytest.mark.story("CAP-022", "AC3")
def test_cidr_ac3_changes_compare_comment_and_expiry():
    assert cidr_changes({"cidr": "x", "comment": "a"}, {"cidr": "x", "comment": "a"}) == []
    assert cidr_changes({"cidr": "x"}, {"cidr": "x", "comment": ""}) == []  # omitted comment = none
    # same instant, different spelling
    assert cidr_changes({"expiresAt": "2026-12-31T23:59:59Z"}, {"expiresAt": "2026-12-31T23:59:59.000+00:00"}) == []
    got = cidr_changes({"comment": "b"}, {"comment": "a", "expiresAt": "2026-12-31T23:59:59Z"})
    assert [(c.path, c.before, c.after) for c in got] == [("comment", "a", "b"),
                                                         ("expiresAt", "2026-12-31T23:59:59Z", None)]


@pytest.mark.story("CAP-022", "AC1")
def test_cidr_ac1_create_body_omits_empty_fields():
    assert create_body({"cidr": "203.0.113.10", "comment": ""}) == {"cidr": "203.0.113.10/32"}
