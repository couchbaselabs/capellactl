"""CAP-025 AC6: offline naming rules for scopes and collections (validate exits 3)."""
from __future__ import annotations

import pytest

from capellactl.config.crossref import keyspace_name_issue
from tests.conftest import MINIMAL

RULE = "1–251 characters of A-Z a-z 0-9 _ - %, not starting with _ or %"


@pytest.mark.story("CAP-025", "AC6")
@pytest.mark.parametrize("name", ["_mine", "my scope", "%pct", "a" * 252, "orders/x", ""])
def test_scope_validate_ac6_names(name):
    msg = keyspace_name_issue("scope", name)
    assert msg is not None and RULE in msg and "(_default is the only exception)" in msg
    assert keyspace_name_issue("collection", name) is not None


@pytest.mark.story("CAP-025", "AC6")
@pytest.mark.parametrize("name", ["inventory", "a" * 251, "Items_2024-v%1", "x"])
def test_scope_validate_ac6_valid_names(name):
    assert keyspace_name_issue("scope", name) is None
    assert keyspace_name_issue("collection", name) is None


@pytest.mark.story("CAP-025", "AC6")
def test_scope_validate_ac6_default_scope_only():
    assert keyspace_name_issue("scope", "_default") is None
    assert keyspace_name_issue("scope", "_system") is not None
    assert keyspace_name_issue("collection", "_default") is not None


@pytest.mark.story("CAP-025", "AC6")
@pytest.mark.parametrize(("scope", "collection", "expected"), [
    ("_mine", "items", "scope name '_mine' is not valid"),
    ("my scope", "items", "scope name 'my scope' is not valid"),
    ("inventory", "_items", "collection name '_items' is not valid"),
    ("a" * 252, "items", "must be at most 251 characters"),
])
def test_scope_validate_ac6_validate_exits_3(run, write_config, scope, collection, expected):
    write_config(MINIMAL + "    buckets:\n      - name: orders\n        scopes:\n"
                           f"          - name: \"{scope}\"\n            collections:\n"
                           f"              - name: \"{collection}\"\n")
    r = run("validate")
    assert r.exit_code == 3
    assert expected in r.output
