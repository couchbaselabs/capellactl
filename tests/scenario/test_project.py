"""CAP-009: ensure project."""
from __future__ import annotations

import pytest

from tests.conftest import MINIMAL, seed_healthy

PROJECT_ONLY = """\
apiVersion: capellactl/v1
organizationId: ${CAPELLA_ORG_ID}
project:
  name: nova-dev
  description: Nova development environment
"""


@pytest.mark.story("CAP-009", "AC1")
def test_project_ac1_create_when_missing(fake, run, write_config):
    write_config()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "  + project nova-dev" in r.output
    first = fake.writes()[0]
    assert (first.method, first.path) == ("POST", "/v4/organizations/org-1/projects")
    assert first.body == {"name": "nova-dev", "description": "Nova development environment"}
    pid = next(iter(fake.projects))
    assert fake.writes()[1].path == f"/v4/organizations/org-1/projects/{pid}/clusters"


@pytest.mark.story("CAP-009", "AC2")
def test_project_ac2_update_description_with_if_match(fake, run, write_config):
    pid = fake.seed_project("nova-dev", description="old")
    write_config(PROJECT_ONLY)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert '~ project nova-dev' in r.output and 'description:  "old" → "Nova development environment"' in r.output
    put = fake.calls("PUT", f"*/projects/{pid}")[0]
    assert put.body == {"name": "nova-dev", "description": "Nova development environment"}
    assert put.headers["If-Match"] == "1"


@pytest.mark.story("CAP-009", "AC3")
def test_project_ac3_omitted_description_untouched(fake, run, write_config):
    fake.seed_project("nova-dev", description="kept")
    write_config(PROJECT_ONLY.replace("  description: Nova development environment\n", ""))
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0 and "= project nova-dev" in r.output


@pytest.mark.story("CAP-009", "AC4")
def test_project_ac4_ambiguous_blocked(fake, run, write_config):
    fake.seed_project("nova-dev")
    fake.seed_project("nova-dev")
    write_config(PROJECT_ONLY)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4 and "add id: under project: to choose one" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-009", "AC5")
def test_project_ac5_pinned_id_rename(fake, run, write_config):
    pid = fake.seed_project("nova-old", description="Nova development environment")
    write_config(PROJECT_ONLY.replace("  name: nova-dev\n", f"  id: {pid}\n  name: nova-dev\n"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert 'name:  "nova-old" → "nova-dev"' in r.output
    assert fake.projects[pid]["name"] == "nova-dev"


@pytest.mark.story("CAP-009", "AC5")
def test_project_ac5_pinned_id_missing_never_creates(fake, run, write_config):
    write_config(PROJECT_ONLY.replace("  name: nova-dev\n", "  id: p-404\n  name: nova-dev\n"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 1 and "project p-404 not found" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-009", "AC6")
def test_project_cli_ac6_list_table_and_json(fake, run, write_config):
    for n in ("a", "b", "c"):
        fake.seed_project(n, description=f"{n} desc")
    r = run("project", "list")
    assert r.exit_code == 0
    assert r.output.splitlines()[0].split() == ["S.NO", "NAME", "DESCRIPTION", "CREATED", "IN", "FILE", "ID"]
    assert len(r.output.strip().splitlines()) == 4
    rows = [ln.split() for ln in r.output.splitlines()[1:]]
    assert [row[0] for row in rows] == ["1", "2", "3"] and all(row[-1] in fake.projects for row in rows)
    r = run("-o", "json", "project", "list")
    import json
    assert [p["name"] for p in json.loads(r.output)] == ["a", "b", "c"]


@pytest.mark.story("CAP-009", "AC6")
def test_project_cli_ac6_get_by_name(fake, run):
    pid = fake.seed_project("nova-dev", description="d")
    r = run("project", "get", "nova-dev")
    assert r.exit_code == 0 and pid in r.output and "nova-dev" in r.output


@pytest.mark.story("CAP-009", "AC7")
def test_project_ac7_rerun_zero_writes(fake, run, write_config):
    write_config(PROJECT_ONLY)
    assert run("--auto-approve", "apply").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0 and "No changes" in r.output
    assert fake.writes() == []


def test_project_apply_command_targets_project_only(fake, run, write_config):
    write_config(MINIMAL)
    r = run("--auto-approve", "project", "apply")
    assert r.exit_code == 0, r.output
    assert [c.path.split("/")[-1] for c in fake.writes()] == ["projects"]


def test_project_seed_healthy_noop(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL)
    assert run("plan", "--detailed-exitcode").exit_code == 0
