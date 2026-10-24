"""CAP-039: create a project from the CLI."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from capellactl.cli import console
from tests.conftest import file_projects, seed_healthy

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "getting-started.md"


@pytest.mark.story("CAP-039", "AC1")
def test_project_create_ac1_interactive(fake, run, tmp_path, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("project", "create", "nova-qa", input="QA environment\ny\n")
    assert r.exit_code == 0, r.output
    assert "+ project nova-qa  QA environment" in r.output
    assert "Create project nova-qa in Capella and write capella.yaml? [y/N]" in r.output
    posts = fake.calls("POST", "*/projects")
    assert len(posts) == 1 and posts[0].body == {"name": "nova-qa", "description": "QA environment"}
    data = yaml.safe_load((tmp_path / "capella.yaml").read_text(encoding="utf-8"))
    assert data["projects"] == [{"name": "nova-qa", "description": "QA environment", "clusters": []}]
    assert "capellactl cluster create NAME" in (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert r.output.rstrip().endswith("Next: capellactl cluster create NAME --project nova-qa    "
                                      "(deploys the first cluster of this project)")


@pytest.mark.story("CAP-039", "AC2")
def test_project_create_ac2_auto_approve(fake, run, tmp_path):
    r = run("--auto-approve", "project", "create", "nova-qa", "--description", "QA")
    assert r.exit_code == 0, r.output
    assert [p["name"] for p in fake.projects.values()] == ["nova-qa"]
    assert (tmp_path / "capella.yaml").exists()


@pytest.mark.story("CAP-039", "AC2")
def test_project_create_ac2_needs_auto_approve(fake, run, tmp_path):
    r = run("project", "create", "nova-qa", "--description", "QA")
    assert r.exit_code == 1 and "without approval; pass --auto-approve" in r.output
    assert fake.writes() == [] and not (tmp_path / "capella.yaml").exists()


@pytest.mark.story("CAP-039", "AC3")
def test_project_create_ac3_existing_name(fake, run, tmp_path):
    fake.seed_project("nova-qa")
    r = run("--auto-approve", "project", "create", "nova-qa")
    assert r.exit_code == 4
    assert "project nova-qa already exists; to add it to capella.yaml run 'capellactl sync --project nova-qa'" in r.output
    assert fake.writes() == [] and not (tmp_path / "capella.yaml").exists()


@pytest.mark.story("CAP-039", "AC4")
def test_project_create_ac4_adds_to_existing_file(fake, run, tmp_path):
    seed_healthy(fake)
    run("import")
    before = file_projects(tmp_path / "capella.yaml")
    r = run("--auto-approve", "project", "create", "nova-qa")
    assert r.exit_code == 0, r.output
    after = file_projects(tmp_path / "capella.yaml")
    assert after[0] == before[0] and [p["name"] for p in after] == ["nova-dev", "nova-qa"]
    assert (tmp_path / "capella.yaml.bak").exists()
    r = run("--auto-approve", "--config", "other.yaml", "project", "create", "nova-perf")
    assert r.exit_code == 0 and [p["name"] for p in file_projects(tmp_path / "other.yaml")] == ["nova-perf"]


@pytest.mark.story("CAP-039", "AC5")
def test_project_create_ac5_then_cluster_create(fake, run, tmp_path):
    assert run("--auto-approve", "project", "create", "nova-qa").exit_code == 0
    assert run("plan", "--detailed-exitcode").exit_code == 0
    r = run("--auto-approve", "cluster", "create", "nova-qa-01")
    assert r.exit_code == 0 and "cluster nova-qa-01: healthy" in r.output, r.output
    pid = next(p for p, v in fake.projects.items() if v["name"] == "nova-qa")
    assert [c["project"] for c in fake.clusters.values()] == [pid]
    assert "No changes" in run("--auto-approve", "apply").output


@pytest.mark.story("CAP-039", "AC6")
def test_project_create_ac6_help_and_readme(run):
    assert "  create  " in run("project", "--help").output
    readme = GUIDE.read_text(encoding="utf-8")
    assert "capellactl project create" in readme and "capellactl project list" in readme
