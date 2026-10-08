"""CAP-005: plan engine."""
from __future__ import annotations

import pytest

from tests.conftest import MINIMAL, seed_healthy
from tests.scenario.helpers import FULL, validate_json


def _seed_partial(fake):
    """Project + cluster (3 nodes) + bucket 'events' with scope 'inventory'; 'orders' etc. missing."""
    pid, cid = seed_healthy(fake)
    bid = fake.seed_bucket(cid, "events", memoryAllocationInMb=512)
    fake.scopes[(cid, bid)]["inventory"] = {}
    return pid, cid


@pytest.mark.story("CAP-005", "AC1")
def test_plan_ac1_symbols_and_summary(fake, run, write_config, stub_tree):
    _seed_partial(fake)
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 5") + """\
    buckets:
      - name: events
        memoryAllocationInMb: 512
        scopes:
          - name: inventory
      - name: orders
        memoryAllocationInMb: 1024
""")
    r = run("plan")
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert "  ~ cluster nova-dev-01   scale out" in lines
    i = lines.index("  ~ cluster nova-dev-01   scale out")
    assert lines[i + 1] == "      serviceGroups[data,index,query].numOfNodes:  3 → 5"
    assert "  + bucket nova-dev-01/orders  couchbase · 1024 MB · 1 replica · durability none" in lines
    assert "  = scope nova-dev-01/events/inventory" in lines
    assert "Plan: 1 to add, 1 to change, 0 to delete, 0 blocked." in lines


@pytest.mark.story("CAP-005", "AC2")
def test_plan_ac2_only_get_requests(fake, run, write_config, stub_tree):
    _seed_partial(fake)
    write_config(FULL.replace("numOfNodes: 3", "numOfNodes: 5"))
    assert run("plan").exit_code == 0
    assert fake.calls() and fake.writes() == []


@pytest.mark.story("CAP-005", "AC5")
def test_planner_ac5_ambiguous_name_blocked(fake, run, write_config):
    pid = fake.seed_project("nova-dev", description="Nova development environment")
    a = fake.seed_cluster(pid, "nova-dev-01")
    b = fake.seed_cluster(pid, "nova-dev-01")
    write_config()
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 4
    assert f"! cluster nova-dev-01  2 clusters share this name (ids: {a}, {b}); add id: to choose one" in r.output


@pytest.mark.story("CAP-005", "AC5")
def test_planner_ac5_ambiguous_project_blocked(fake, run, write_config):
    p1, p2 = fake.seed_project("nova-dev"), fake.seed_project("nova-dev")
    write_config()
    r = run("plan")
    assert r.exit_code == 4
    assert f"2 projects share this name (ids: {p1}, {p2}); add id: under project: to choose one" in r.output


@pytest.mark.story("CAP-005", "AC6")
def test_planner_ac6_children_of_new_cluster(fake, run, write_config, stub_tree):
    fake.seed_project("nova-dev", description="Nova development environment")
    write_config(FULL)
    r = run("plan")
    assert r.exit_code == 0, r.output
    assert "  + bucket nova-dev-01/orders  couchbase · 1024 MB · 1 replica · durability none  (after cluster is healthy)" in r.output
    assert "  + credential nova-dev-01/orders_app  read+write · orders  (after cluster is healthy)" in r.output
    assert "  + scope nova-dev-01/orders/billing  (after bucket is created)" in r.output
    assert not [c for c in fake.calls() if "/clusters/" in c.path]


@pytest.mark.story("CAP-005", "AC6")
def test_planner_ac6_unsupported_kinds_deferred(fake, run, tmp_path):
    import shutil

    from tests.conftest import EXAMPLE

    seed_healthy(fake, configurationType="multiNode")
    shutil.copy(EXAMPLE, tmp_path / "capella.yaml")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "reporting_ro.txt").write_text("R3port!ng-pw")
    r = run("plan", extra_env={"ORDERS_APP_PASSWORD": "Orders#App-123"})
    assert r.exit_code == 0, r.output
    assert "  + bucket nova-dev-01/orders  couchbase · magma · 1024 MB · 1 replica · durability majority" in r.output
    assert "  + scope nova-dev-01/orders/inventory  (after bucket is created)" in r.output  # real since CAP-025
    assert "  + collection nova-dev-01/orders/inventory/suppliers  maxTTL -1  (after scope is created)" in r.output
    # every kind in the example is real now (the schedule since CAP-020)
    assert "  + schedule nova-dev-01  US/Pacific · Mon–Thu 08:00–18:00 · Fri 08:00–14:30 · Sat–Sun off" in r.output
    assert "deferred" not in r.output


@pytest.mark.story("CAP-005", "AC6")
def test_planner_ac6_unsupported_kind_shown_deferred(fake, run, write_config, monkeypatch):
    """The deferred mechanism stays for kinds a build does not manage (none in 1.0 now)."""
    from capellactl.cli import env as env_mod
    from capellactl.resources.cluster import ClusterReconciler
    from capellactl.resources.project import ProjectReconciler
    from capellactl.resources.unsupported import UnsupportedReconciler

    def tree():
        later = UnsupportedReconciler("schedule", "CAP-999", lambda c: [c["hibernation"]] if c.get("hibernation")
                                      else [], lambda v: "hibernation schedule")
        return ProjectReconciler(children=[ClusterReconciler(children=[later])])

    monkeypatch.setattr(env_mod, "TREE_FACTORY", tree)
    seed_healthy(fake)
    write_config(MINIMAL + "    hibernation: { timezone: US/Pacific, weekdays: \"08:00-18:00\", weekend: \"off\" }\n")
    r = run("plan")
    assert "… schedule nova-dev-01  hibernation schedule — not managed by this build yet (CAP-999)" in r.output
    assert "deferred." in r.output


@pytest.mark.story("CAP-005", "AC7")
def test_planner_ac7_target_filter(fake, run, write_config, stub_tree):
    _seed_partial(fake)
    write_config(FULL.replace("numOfNodes: 3", "numOfNodes: 5"))
    r = run("plan", "--target", "bucket/nova-dev-01/orders")
    assert r.exit_code == 0, r.output
    body = [line for line in r.output.splitlines() if line.startswith("  ")]
    assert body[0] == "  + bucket nova-dev-01/orders  couchbase · 1024 MB · 1 replica · durability none"
    assert not any("cluster nova-dev-01" in line or "events" in line or "credential" in line for line in body)


@pytest.mark.story("CAP-005", "AC8")
def test_plan_ac8_json_schema(fake, run, write_config, stub_tree):
    _seed_partial(fake)
    write_config(FULL.replace("numOfNodes: 3", "numOfNodes: 5"))
    r = run("-o", "json", "plan")
    data = validate_json("plan.schema.json", r.output)
    kinds = {(a["kind"], a["action"]) for a in data["plan"]["actions"]}
    assert ("cluster", "update") in kinds and ("bucket", "create") in kinds


@pytest.mark.story("CAP-005", "AC8")
def test_plan_ac8_detailed_exitcode(fake, run, write_config):
    seed_healthy(fake)
    write_config()
    assert run("plan", "--detailed-exitcode").exit_code == 0
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4"))
    assert run("plan", "--detailed-exitcode").exit_code == 2
    write_config(MINIMAL.replace("us-east-1", "eu-west-1"))
    assert run("plan", "--detailed-exitcode").exit_code == 4
