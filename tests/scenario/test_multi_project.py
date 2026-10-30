"""CAP-040: several projects in one capella.yaml."""
from __future__ import annotations

import json

import pytest

from capellactl.cli import console
from tests.conftest import MINIMAL, file_clusters, file_projects, seed_healthy


def _two_projects(fake):
    demo, _ = seed_healthy(fake)
    np = fake.seed_project("non-prod", description="Non-production")
    fake.seed_cluster(np, "np-01")
    return demo, np


@pytest.mark.story("CAP-040", "AC2")
def test_multi_ac2_legacy_still_plans(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL)  # single-project form
    assert run("validate").exit_code == 0
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0 and "Project nova-dev · organization org-1" in r.output


@pytest.mark.story("CAP-040", "AC2")
def test_multi_ac2_converted_on_first_write(fake, run, write_config, tmp_path):
    seed_healthy(fake)
    write_config(MINIMAL)
    assert run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "4").exit_code == 0
    text = (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert "projects:" in text and "\nproject:" not in text
    assert file_clusters(tmp_path / "capella.yaml")[0]["serviceGroups"][0]["numOfNodes"] == 4
    assert "\nproject:" in (tmp_path / "capella.yaml.bak").read_text(encoding="utf-8")
    assert run("plan", "--detailed-exitcode").exit_code == 0


@pytest.mark.story("CAP-040", "AC3")
def test_multi_ac3_plan_apply_two_projects(fake, run, tmp_path):
    seed_healthy(fake)
    run("import")
    assert run("--auto-approve", "project", "create", "non-prod").exit_code == 0
    assert run("--auto-approve", "--no-wait", "cluster", "create", "np-01", "--project", "non-prod",
               "--no-apply").exit_code == 0
    r = run("plan")
    assert "Projects nova-dev, non-prod" in r.output
    assert "  = project nova-dev" in r.output and "  = project non-prod" in r.output
    assert "  + cluster np-01" in r.output
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output and fake.writes() == []


@pytest.mark.story("CAP-040", "AC3")
def test_multi_ac3_target_qualified_cluster(fake, run, tmp_path):
    demo, np = fake.seed_project("demo"), fake.seed_project("non-prod")
    fake.seed_cluster(demo, "main")
    fake.seed_cluster(np, "main")
    run("import")
    path = tmp_path / "capella.yaml"
    text = path.read_text(encoding="utf-8")
    i = text.index("name: non-prod")
    path.write_text(text[:i] + text[i:].replace("numOfNodes: 3", "numOfNodes: 4", 1), encoding="utf-8")
    r = run("plan", "--target", "cluster/non-prod/main")
    assert "~ cluster main" in r.output and r.output.count("cluster main") == 1
    r = run("plan", "--target", "cluster/demo/main")
    assert "~ cluster main" not in r.output


@pytest.mark.story("CAP-040", "AC4")
def test_multi_ac4_project_create_appends(fake, run, tmp_path):
    seed_healthy(fake)
    run("import")
    before = file_projects(tmp_path / "capella.yaml")[0]
    r = run("--auto-approve", "project", "create", "non-prod", "--description", "NP")
    assert r.exit_code == 0, r.output
    projects = file_projects(tmp_path / "capella.yaml")
    assert projects[0] == before
    assert projects[1] == {"name": "non-prod", "description": "NP", "clusters": []}


@pytest.mark.story("CAP-040", "AC5")
def test_multi_ac5_import_all_projects(fake, run, tmp_path):
    _two_projects(fake)
    fake.seed_project("sandbox")
    r = run("import")
    assert r.exit_code == 0 and "Imported 3 projects, 2 clusters" in r.output, r.output
    assert [p["name"] for p in file_projects(tmp_path / "capella.yaml")] == ["nova-dev", "non-prod", "sandbox"]
    assert run("plan", "--detailed-exitcode").exit_code == 0


@pytest.mark.story("CAP-040", "AC5")
def test_multi_ac5_import_merges_missing(fake, run, tmp_path):
    _two_projects(fake)
    assert run("import", "--project", "nova-dev").exit_code == 0
    path = tmp_path / "capella.yaml"
    before = file_projects(path)[0]
    r = run("import")  # an alias of sync since CAP-054: refreshes nova-dev and adds the missing project
    assert r.exit_code == 0, r.output
    assert "added project non-prod (1 cluster)" in r.output
    projects = file_projects(path)
    assert projects[0] == before and [p["name"] for p in projects] == ["nova-dev", "non-prod"]
    r = run("import")
    assert "already in sync with Capella: 2 projects, 2 clusters" in r.output
    assert run("plan", "--detailed-exitcode").exit_code == 0


@pytest.mark.story("CAP-040", "AC6")
def test_multi_ac6_sync_all_projects(fake, run, tmp_path):
    _two_projects(fake)
    run("import")
    for c in fake.clusters.values():
        c["body"]["description"] = f"changed {c['body']['name']}"
    r = run("sync", "--project", "non-prod")
    assert r.exit_code == 0
    cl = {c["name"]: c for c in file_clusters(tmp_path / "capella.yaml")}
    assert cl["np-01"]["description"] == "changed np-01" and cl["nova-dev-01"]["description"] != "changed nova-dev-01"
    r = run("sync")
    cl = {c["name"]: c for c in file_clusters(tmp_path / "capella.yaml")}
    assert cl["nova-dev-01"]["description"] == "changed nova-dev-01"
    assert "already in sync" in run("sync").output


@pytest.mark.story("CAP-040", "AC7")
def test_multi_ac7_cluster_create_project_choice(fake, run, tmp_path, monkeypatch):
    _two_projects(fake)
    run("import")
    r = run("--auto-approve", "cluster", "create", "new-01")
    assert r.exit_code == 3 and "several projects (nova-dev, non-prod); pass --project NAME" in r.output
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "create", "new-01", input="2\n\n\n\n\n\n\ny\n")
    assert r.exit_code == 0, r.output
    assert "new-01" in [c["name"] for c in file_clusters(tmp_path / "capella.yaml", "non-prod")]


@pytest.mark.story("CAP-040", "AC7")
def test_multi_ac7_same_cluster_name_needs_project(fake, run, tmp_path):
    demo, np = fake.seed_project("demo"), fake.seed_project("non-prod")
    fake.seed_cluster(demo, "main")
    fake.seed_cluster(np, "main")
    run("import")
    r = run("--auto-approve", "cluster", "scale", "main", "--nodes", "4")
    assert r.exit_code == 3 and "cluster main is in several projects (demo, non-prod); pass --project NAME" in r.output
    r = run("--auto-approve", "cluster", "scale", "main", "--nodes", "4", "--project", "non-prod")
    assert r.exit_code == 0, r.output
    assert file_clusters(tmp_path / "capella.yaml", "non-prod")[0]["serviceGroups"][0]["numOfNodes"] == 4
    assert file_clusters(tmp_path / "capella.yaml", "demo")[0]["serviceGroups"][0]["numOfNodes"] == 3
    r = run("cluster", "get", "main", "--project", "demo")
    assert r.exit_code == 0 and "main" in r.output


@pytest.mark.story("CAP-040", "AC8")
def test_multi_ac8_project_list_in_file(fake, run):
    _two_projects(fake)
    fake.seed_project("sandbox")
    run("import", "--project", "nova-dev", "--project", "non-prod")
    rows = {line.split()[1]: line.split()[-2] for line in run("project", "list").output.splitlines()[1:]}
    assert rows == {"nova-dev": "yes", "non-prod": "yes", "sandbox": "-"}


def test_multi_cluster_get_infers_project(fake, run):
    _two_projects(fake)
    run("import")
    r = run("cluster", "get", "np-01")
    assert r.exit_code == 0 and "np-01" in r.output


@pytest.mark.story("CAP-040", "AC7")
def test_multi_ac7_cluster_list_every_project(fake, run):
    _two_projects(fake)
    run("import")
    r = run("cluster", "list")
    assert r.exit_code == 0, r.output
    assert "pass --project" not in r.output
    rows = [line.split()[:3] for line in r.output.splitlines()]
    assert rows == [["S.NO", "NAME", "PROJECT"], ["1", "np-01", "non-prod"], ["2", "nova-dev-01", "nova-dev"]]  # by project
    r = run("cluster", "list", "--project", "non-prod")
    assert [line.split()[:3] for line in r.output.splitlines()[1:]] == [["1", "np-01", "non-prod"]]
    data = json.loads(run("-o", "json", "cluster", "list").output)
    assert [(c["projectName"], c["name"]) for c in data] == [("non-prod", "np-01"), ("nova-dev", "nova-dev-01")]
