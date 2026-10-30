"""Resource groups use list/get/create/update/delete; apply is the whole-file command (architecture section 5)."""
from __future__ import annotations

import pytest

from tests.conftest import MINIMAL, seed_healthy


@pytest.mark.parametrize(("group", "verbs"), [
    ("project", {"list", "get", "create", "update", "delete"}),
    ("cluster", {"list", "get", "create", "clone", "update", "delete", "options", "scale", "protect", "power",
                 "schedule", "group", "disk-types", "backup"}),
    ("cidr", {"list", "create", "delete"}),
    ("bucket", {"list", "get", "create", "update", "delete", "backup"}),
    ("scope", {"list", "create", "delete"}),
    ("collection", {"list", "create", "update", "delete"}),
    ("credential", {"list", "get", "create", "update", "delete"}),
])
def test_groups_list_crud_verbs_without_apply(run, group, verbs):
    r = run(group, "-h")
    assert r.exit_code == 0
    listed = r.output.split("Commands:")[1].split("Examples:")[0]
    assert {line.split()[0] for line in listed.splitlines() if line.strip()} == verbs


def test_project_update_records_and_applies(fake, run, write_config, tmp_path):
    pid, _ = seed_healthy(fake)
    write_config()
    r = run("--auto-approve", "project", "update", "nova-dev", "--description", "Nova dev, renamed")
    assert r.exit_code == 0, r.output
    assert fake.projects[pid]["description"] == "Nova dev, renamed"
    assert "description: Nova dev, renamed" in (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    assert [c.method for c in fake.writes()] == ["PUT"]  # the project only, not its clusters


def test_hidden_apply_aliases_still_work(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL)
    assert run("project", "apply").exit_code == 0
    assert run("cluster", "apply", "nova-dev-01").exit_code == 0
    assert fake.writes() == []


@pytest.mark.story("CAP-009", "AC2")
def test_project_update_cluster_name_given_points_to_project(fake, run, write_config):
    seed_healthy(fake)
    p = write_config()
    before = p.read_text(encoding="utf-8")
    r = run("project", "update", "nova-dev-01", "--description", "Live demo")
    assert r.exit_code == 3
    assert ("nova-dev-01 is a cluster in project nova-dev, not a project. Did you mean: "
            'capellactl project update nova-dev --description "Live demo"') in r.output
    assert "import --project nova-dev-01" not in r.output
    assert p.read_text(encoding="utf-8") == before and fake.writes() == []
    r = run("project", "get", "nova-dev-01")
    assert r.exit_code == 1 and "is a cluster in project nova-dev, not a project. Did you mean: project nova-dev" in r.output
    r = run("project", "update", "nope", "--description", "x")
    assert "add it with 'capellactl sync --project nope'" in r.output


@pytest.mark.story("CAP-009", "AC2")
def test_project_option_cluster_name_given_points_to_project(fake, run, write_config):
    seed_healthy(fake)
    write_config()
    r = run("cluster", "create", "nova-dev-02", "--project", "nova-dev-01")
    assert r.exit_code == 3
    assert "nova-dev-01 is a cluster in project nova-dev, not a project. Did you mean: --project nova-dev" in r.output
    assert fake.writes() == []
