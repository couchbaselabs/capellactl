"""CAP-025 AC2–AC4: collection diff rules (maxTTL compared only when declared; server version gate)."""
from __future__ import annotations

from typing import Any

import pytest

from capellactl.resources.base import Action, ActionType, Observed
from capellactl.resources.scope import (
    CollectionReconciler,
    ScopeReconciler,
    is_system_collection,
    is_system_scope,
    parse_version,
)


def _scope(version: str | None = "8.0.1") -> Action:
    body: dict[str, Any] = {"name": "nova-dev-01"}
    if version:
        body["couchbaseServer"] = {"version": version}
    cluster = Action("cluster", "nova-dev-01", ActionType.NOOP, None, observed=Observed("c-1", body))  # type: ignore[arg-type]
    bucket = Action("bucket", "nova-dev-01/orders", ActionType.NOOP, None, parent=cluster)  # type: ignore[arg-type]
    return Action("scope", "nova-dev-01/orders/inventory", ActionType.NOOP, None,  # type: ignore[arg-type]
                  desired={"name": "inventory"}, parent=bucket)


def _diff(desired: dict[str, Any], observed: dict[str, Any], version: str | None = "8.0.1") -> Action:
    return CollectionReconciler().diff(None, desired, Observed(observed["name"], observed), _scope(version))  # type: ignore[arg-type]


@pytest.mark.story("CAP-025", "AC4")
def test_collections_ac4_omitted_maxttl_noop():
    a = _diff({"name": "items"}, {"name": "items", "maxTTL": 3600})
    assert a.type is ActionType.NOOP and a.changes == []


@pytest.mark.story("CAP-025", "AC4")
def test_collections_ac4_declared_maxttl_compared():
    assert _diff({"name": "items", "maxTTL": 3600}, {"name": "items", "maxTTL": 3600}).type is ActionType.NOOP
    a = _diff({"name": "items", "maxTTL": 0}, {"name": "items", "maxTTL": 3600})
    assert a.type is ActionType.UPDATE and [(c.path, c.before, c.after) for c in a.changes] == [("maxTTL", 3600, 0)]


@pytest.mark.story("CAP-025", "AC3")
@pytest.mark.parametrize(("version", "expected"), [("7.2.4", ActionType.BLOCKED), ("7.6.0", ActionType.UPDATE),
                                                   ("7.6.2-1234", ActionType.UPDATE), (None, ActionType.UPDATE)])
def test_collections_ac3_version_gate(version, expected):
    assert _diff({"name": "s", "maxTTL": -1}, {"name": "s", "maxTTL": 0}, version).type is expected


@pytest.mark.story("CAP-025", "AC1")
def test_collections_ac1_create_summary():
    rec = CollectionReconciler()
    assert rec.diff(None, {"name": "items"}, None, _scope()).summary is None  # type: ignore[arg-type]
    assert rec.diff(None, {"name": "s", "maxTTL": -1}, None, _scope()).summary == "maxTTL -1"  # type: ignore[arg-type]


@pytest.mark.story("CAP-025", "AC5")
def test_scopes_ac5_system_objects():
    assert is_system_scope("_default") and is_system_scope("_system") and not is_system_scope("inventory")
    assert is_system_collection("_default", "_default") and is_system_collection("_system", "_mobile")
    assert not is_system_collection("_default", "legacy")
    rec = ScopeReconciler()
    assert not rec.manages(Observed("_system", {"name": "_system"}))
    assert not rec.manages(Observed("_default", {"name": "_default"}))
    assert rec.manages(Observed("legacy", {"name": "legacy"}))
    a = rec.diff(None, {"name": "_default"}, None, None)  # type: ignore[arg-type]
    assert a.type is ActionType.NOOP  # never created


def test_parse_version():
    assert parse_version("7.6.2") == (7, 6, 2)
    assert parse_version("7.2.4-build-12") == (7, 2, 4)
    assert parse_version(None) is None
