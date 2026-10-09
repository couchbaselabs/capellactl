"""CAP-010: delete a project."""
from __future__ import annotations

import pytest

from capellactl.cli import console
from tests.conftest import file_projects, seed_healthy


@pytest.fixture
def two(fake, run, tmp_path):
    """capella.yaml with nova-dev (one cluster) and an empty non-prod."""
    seed_healthy(fake)
    assert run("import").exit_code == 0
    assert run("--auto-approve", "project", "create", "non-prod").exit_code == 0
    fake.reset_calls()
    return tmp_path / "capella.yaml"


def _pid(fake, name):
    return next(p for p, v in fake.projects.items() if v["name"] == name)


@pytest.mark.story("CAP-010", "AC1")
def test_project_delete_ac1_empty_project(fake, run, two, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    pid = _pid(fake, "non-prod")
    r = run("project", "delete", "non-prod", input="non-prod\n")
    assert r.exit_code == 0, r.output
    assert "deleted project non-prod" in r.output
    assert [(c.method, c.path) for c in fake.writes()] == [("DELETE", f"/v4/organizations/org-1/projects/{pid}")]


@pytest.mark.story("CAP-010", "AC2")
def test_project_delete_ac2_absent_noop(fake, run, two):
    r = run("--auto-approve", "project", "delete", "nope")
    assert r.exit_code == 0 and "project nope not found, nothing to do" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-010", "AC3")
def test_project_delete_ac3_non_empty_blocked(fake, run, two):
    r = run("--auto-approve", "project", "delete", "nova-dev")
    assert r.exit_code == 4
    assert "project nova-dev contains 1 cluster (nova-dev-01). Delete it first or pass --cascade." in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-010", "AC4")
def test_project_delete_ac4_cascade_order(fake, run, two):
    pid = _pid(fake, "nova-dev")
    fake.seed_cluster(pid, "nova-dev-02")
    r = run("--auto-approve", "project", "delete", "nova-dev", "--cascade")
    assert r.exit_code == 0, r.output
    assert "  - cluster nova-dev-02\n  - cluster nova-dev-01\n  - project nova-dev" in r.output
    writes = [(c.method, c.path.rsplit("/", 2)[-2]) for c in fake.writes()]
    assert writes == [("DELETE", "clusters"), ("DELETE", "clusters"), ("DELETE", "projects")]
    gets_between = [c for c in fake.calls("GET", f"*/projects/{pid}/clusters/*")]
    assert gets_between, "must wait for the clusters to be gone before deleting the project"
    assert fake.writes()[0].query.get("retainsnapshotbackups") == ["true"]


@pytest.mark.story("CAP-010", "AC4")
def test_project_delete_ac4_cascade_respects_protection(fake, run, two):
    cid = next(iter(fake.clusters))
    fake.clusters[cid]["body"]["deletionProtection"] = True
    r = run("--auto-approve", "project", "delete", "nova-dev", "--cascade")
    assert r.exit_code == 4 and "! cluster nova-dev-01  deletion protection is on" in r.output
    assert "Nothing was deleted." in r.output and fake.writes() == []


@pytest.mark.story("CAP-010", "AC5")
def test_project_delete_ac5_wrong_name_cancels(fake, run, two, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("project", "delete", "non-prod", input="non-pord\n")
    assert "Type the project name to confirm deletion" in r.output
    assert "Cancelled; nothing was deleted." in r.output and fake.writes() == []
    monkeypatch.setattr(console, "is_interactive", lambda: False)
    r = run("project", "delete", "non-prod")
    assert r.exit_code == 1 and "without approval; pass --auto-approve" in r.output and fake.writes() == []


@pytest.mark.story("CAP-010", "AC6")
def test_project_delete_ac6_api_409_message(fake, run, two):
    fake.fail_next("DELETE", "*/projects/*", 409, code=1010)
    r = run("--auto-approve", "project", "delete", "non-prod")
    assert r.exit_code == 1 and "Capella refused: project is not empty" in r.output and "Hint:" in r.output


@pytest.mark.story("CAP-010", "AC7")
def test_project_delete_ac7_rerun_noop(fake, run, two):
    assert run("--auto-approve", "project", "delete", "non-prod").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "project", "delete", "non-prod")
    assert r.exit_code == 0 and "not found, nothing to do" in r.output and fake.writes() == []


@pytest.mark.story("CAP-010", "AC8")
def test_project_delete_ac8_removed_from_file(fake, run, two):
    before = file_projects(two)[0]
    assert run("--auto-approve", "project", "delete", "non-prod").exit_code == 0
    assert file_projects(two) == [before]
    assert "non-prod" in (two.parent / "capella.yaml.bak").read_text()
    fake.reset_calls()
    assert run("plan", "--detailed-exitcode").exit_code == 0 and fake.writes() == []
    assert run("--auto-approve", "project", "delete", "nova-dev", "--cascade").exit_code == 0
    assert file_projects(two) == [] and run("validate").exit_code == 0


def test_project_delete_free_tier_cluster_cascade(fake, run, two):
    fake.seed_free_cluster(_pid(fake, "non-prod"), "try-01")
    r = run("--auto-approve", "project", "delete", "non-prod", "--cascade")
    assert r.exit_code == 0, r.output
    assert fake.calls("DELETE", "*/clusters/freeTier/*")
