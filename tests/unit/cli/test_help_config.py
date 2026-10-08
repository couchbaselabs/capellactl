"""CAP-034 AC4: field help generated from the schema."""
from __future__ import annotations

import pytest

from capellactl.cli.help import leaf_fields


@pytest.mark.story("CAP-034", "AC4")
def test_help_config_ac4_field_details(run):
    r = run("help", "config", "clusters.buckets.storageBackend")
    assert r.exit_code == 0
    for s in ("type:       string", "allowed:    couchstore, magma", "immutable after creation",
              "API:        storageBackend (Create Bucket)"):
        assert s in r.output
    r = run("help", "config", "clusters[0].serviceGroups[1].numOfNodes")
    assert r.exit_code == 0 and "updatable in place" in r.output and "example:    numOfNodes: 3" in r.output


@pytest.mark.story("CAP-034", "AC4")
def test_help_config_ac4_tree(run):
    r = run("help", "config")
    assert r.exit_code == 0
    assert "capella.yaml fields" in r.output
    assert "storageBackend: string  [immutable]" in r.output
    assert "  clusters: list" in r.output or "clusters: list" in r.output


@pytest.mark.story("CAP-034", "AC4")
def test_help_config_ac4_unknown_path_suggestions(run):
    r = run("help", "config", "clusters.buckets.storagebackend")
    assert r.exit_code == 2
    assert "clusters.buckets.storageBackend" in r.output


@pytest.mark.story("CAP-034", "AC4")
def test_help_config_ac4_every_schema_field_documented():
    missing = [p for p, n in leaf_fields().items() if not n.get("description") or not n.get("x-mutability")]
    assert missing == []
