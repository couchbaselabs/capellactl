"""CAP-041: free-tier clusters and cluster options."""
from __future__ import annotations

import json

import pytest

from capellactl.cli import console
from tests.conftest import file_clusters, seed_healthy


@pytest.fixture
def imported(fake, run, tmp_path):
    seed_healthy(fake)
    assert run("import").exit_code == 0
    return tmp_path / "capella.yaml"


@pytest.mark.story("CAP-041", "AC1")
def test_options_ac1_free_tier_available(fake, run, imported):
    r = run("cluster", "options")
    assert r.exit_code == 0
    assert "Free tier          available" in r.output
    assert "aws    us-east-2, eu-west-1, ap-southeast-1" in r.output
    assert "azure  eastus, swedencentral, koreacentral" in r.output
    assert "in use by your clusters: aws us-east-1" in r.output and "support plans    basic" in r.output
    data = json.loads(run("-o", "json", "cluster", "options").output)
    assert data["freeTier"]["available"] is True and data["freeTier"]["regions"]["gcp"][0] == "us-central1"


@pytest.mark.story("CAP-041", "AC1")
def test_options_ac1_free_tier_used(fake, run, imported):
    other = fake.seed_project("sandbox")
    fake.seed_free_cluster(other, "someone-free")
    r = run("cluster", "options")
    assert "Free tier          not available: already used by someone-free in project sandbox" in r.output
    assert "deploy: capellactl cluster create NAME --free-tier" not in r.output


@pytest.mark.story("CAP-041", "AC2")
def test_free_tier_ac2_create_and_record(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "try-01", "--free-tier", "--provider", "aws", "--region",
            "us-east-2")
    assert r.exit_code == 0, r.output
    posts = fake.calls("POST", "*/clusters/freeTier")
    assert len(posts) == 1
    assert posts[0].body == {"name": "try-01", "cloudProvider": {"type": "aws", "region": "us-east-2",
                                                                 "cidr": "10.0.0.0/24"}}
    assert "cluster try-01: healthy" in r.output
    c = next(c for c in file_clusters(imported) if c["name"] == "try-01")
    assert c["tier"] == "free" and c["id"] in fake.clusters
    fake.reset_calls()
    assert run("plan", "--detailed-exitcode").exit_code == 0 and fake.writes() == []


@pytest.mark.story("CAP-041", "AC3")
def test_free_tier_ac3_interactive_choices(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "create", "try-01", input="free\ngcp\n\n\ny\n")
    assert r.exit_code == 0, r.output
    assert "Cluster type (free, provisioned) [provisioned]" in r.output
    assert "Region (free-tier regions) (us-central1, europe-west1, asia-east1) [us-central1]" in r.output
    assert "Size" not in r.output and "Support plan" not in r.output
    c = next(c for c in file_clusters(imported) if c["name"] == "try-01")
    assert c["cloudProvider"]["region"] == "us-central1"


@pytest.mark.story("CAP-041", "AC3")
def test_free_tier_ac3_not_offered_when_used(fake, run, imported, monkeypatch):
    fake.seed_free_cluster(next(iter(fake.projects)), "already-free")
    r = run("--auto-approve", "cluster", "create", "try-02", "--free-tier")
    assert r.exit_code == 4 and "the free tier is already used by already-free in project nova-dev" in r.output
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "create", "prov-01", input="\n\n\n\n\ny\n")
    assert "Cluster type" not in r.output and r.exit_code == 0, r.output


@pytest.mark.story("CAP-041", "AC5")
def test_free_tier_ac5_update_description(fake, run, imported):
    assert run("--auto-approve", "cluster", "create", "try-01", "--free-tier").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "update", "try-01", "--description", "for testing")
    assert r.exit_code == 0, r.output
    puts = fake.calls("PUT", "*/clusters/freeTier/*")
    assert len(puts) == 1 and puts[0].body == {"name": "try-01", "description": "for testing"}
    assert not fake.calls("PUT", "*/clusters/c-*")


@pytest.mark.story("CAP-041", "AC5")
def test_free_tier_ac5_scale_refused(fake, run, imported):
    assert run("--auto-approve", "cluster", "create", "try-01", "--free-tier").exit_code == 0
    fake.reset_calls()
    for args in (("cluster", "scale", "try-01", "--nodes", "3"),
                 ("cluster", "update", "try-01", "--cpu", "8"),
                 ("cluster", "update", "try-01", "--support-plan", "enterprise")):
        r = run("--auto-approve", *args)
        assert r.exit_code == 4 and "[ERROR]: free-tier clusters have 1 node and a fixed size" in r.output, args
    assert fake.writes() == []
    r = run("--auto-approve", "cluster", "create", "x", "--free-tier", "--size", "small")
    assert r.exit_code == 3 and "free-tier clusters have a fixed size and plan" in r.output


@pytest.mark.story("CAP-041", "AC6")
def test_free_tier_ac6_import_round_trip(fake, run, tmp_path):
    pid, _ = seed_healthy(fake)
    fid = fake.seed_free_cluster(pid, "try-01", cloudProvider={"type": "aws", "region": "eu-west-1",
                                                                "cidr": "10.4.0.0/23"})
    assert run("import").exit_code == 0
    c = next(c for c in file_clusters(tmp_path / "capella.yaml") if c["name"] == "try-01")
    assert c == {"id": fid, "name": "try-01", "tier": "free",
                 "cloudProvider": {"type": "aws", "region": "eu-west-1", "cidr": "10.4.0.0/23"}}
    fake.reset_calls()
    assert run("plan", "--detailed-exitcode").exit_code == 0
    assert "already in sync" in run("sync").output and fake.writes() == []
