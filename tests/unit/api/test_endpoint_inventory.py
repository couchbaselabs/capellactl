"""CAP-003 AC9: one function per release endpoint."""
from __future__ import annotations

import inspect

import pytest

from capellactl.api import endpoints as ep

EXPECTED = {
    "list_organizations", "get_organization", "list_projects", "get_project", "create_project", "update_project",
    "delete_project", "list_clusters", "get_cluster", "create_cluster", "update_cluster", "delete_cluster",
    "create_free_cluster", "get_free_cluster", "update_free_cluster", "delete_free_cluster",
    "set_deletion_protection", "turn_cluster_on", "turn_cluster_off", "turn_free_cluster_on", "turn_free_cluster_off",
    "get_cluster_stats", "get_schedule",
    "create_schedule", "update_schedule", "delete_schedule", "pause_schedule", "resume_schedule",
    "list_allowed_cidrs", "get_allowed_cidr", "create_allowed_cidr", "delete_allowed_cidr", "list_buckets",
    "get_bucket", "create_bucket", "update_bucket", "delete_bucket", "list_free_buckets", "get_free_bucket",
    "create_free_bucket", "update_free_bucket", "delete_free_bucket", "list_scopes", "get_scope", "create_scope",
    "delete_scope", "list_collections", "get_collection", "create_collection", "update_collection",
    "delete_collection", "list_credentials", "get_credential", "create_credential", "update_credential",
    "delete_credential",
}


@pytest.mark.story("CAP-003", "AC9")
def test_endpoints_ac9_all_release_endpoints_present():
    funcs = {n for n, f in inspect.getmembers(ep, inspect.isfunction) if f.__module__ == ep.__name__
             and not n.startswith("_") and n != "required_roles"}
    assert funcs == EXPECTED
    assert len(ep.INVENTORY) == len(EXPECTED)
    for n in EXPECTED:
        assert getattr(ep, n).__doc__, f"{n} has no docstring"
