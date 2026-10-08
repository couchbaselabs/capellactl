"""CAP-018: cluster scale --step with min/max guardrails."""
from __future__ import annotations

import pytest

from tests.conftest import MINIMAL, seed_healthy
from tests.scenario.helpers import validate_json

SEARCH = {"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
          "numOfNodes": 2, "services": ["search"]}
WITH_SEARCH = MINIMAL + ("      - node: { compute: { cpu: 4, ram: 16 }, disk: { type: gp3, storage: 50, iops: 3000 } }\n"
                         "        numOfNodes: 2\n        services: [search]\n")


def _nodes(fake, cid):
    return [g["numOfNodes"] for g in fake.clusters[cid]["body"]["serviceGroups"]]


@pytest.mark.story("CAP-018", "AC1")
def test_step_ac1_step_up(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL)
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--step", "+1", "--max", "6")
    assert r.exit_code == 0, r.output
    assert "scaled data,index,query: 3 → 4" in r.output
    assert [c.method for c in fake.writes()] == ["PUT"] and _nodes(fake, cid) == [4]


@pytest.mark.story("CAP-018", "AC2")
def test_step_ac2_step_down_runs_guards(fake, run, write_config):
    _, cid = seed_healthy(fake, nodes=4)
    write_config(MINIMAL)
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--step", "-1", "--min", "3")
    assert r.exit_code == 0, r.output
    assert "checks: memory ok" in r.output and "scaled data,index,query: 4 → 3" in r.output
    assert _nodes(fake, cid) == [3]


@pytest.mark.story("CAP-018", "AC2")
def test_step_ac2_step_down_guard_blocks(fake, run, write_config):
    _, cid = seed_healthy(fake, nodes=4)
    fake.seed_bucket(cid, "orders", replicas=3)
    write_config(MINIMAL)
    r = run("--auto-approve", "-o", "json", "cluster", "scale", "nova-dev-01", "--step", "-1")
    assert r.exit_code == 4
    assert '"status": "blocked"' in r.output and fake.writes() == []


@pytest.mark.story("CAP-018", "AC3")
def test_step_ac3_at_max_noop(fake, run, write_config):
    seed_healthy(fake, nodes=6)
    write_config(MINIMAL)
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--step", "+1", "--max", "6")
    assert r.exit_code == 0 and "already at maximum (6)" in r.output, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-018", "AC3")
def test_step_ac3_at_min_noop(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL)
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--step", "-1")
    assert r.exit_code == 0 and "already at minimum (3)" in r.output, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-018", "AC4")
def test_step_ac4_all_groups_individual(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.clusters[cid]["body"]["serviceGroups"].append(SEARCH)
    write_config(WITH_SEARCH)
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--step", "+1", "--all-groups")
    assert r.exit_code == 0, r.output
    [put] = [c for c in fake.writes() if c.method == "PUT"]
    assert [g["numOfNodes"] for g in put.body["serviceGroups"]] == [4, 3]  # each group +1, not both set to 6
    assert "scaled data,index,query: 3 → 4" in r.output and "scaled search: 2 → 3" in r.output


@pytest.mark.story("CAP-018", "AC5")
def test_step_ac5_waits_when_busy(fake, run, write_config):
    _, cid = seed_healthy(fake, nodes=4)  # a scale to 4 is still running
    fake.set_transition(cid, ["scaling", "healthy"])
    write_config(MINIMAL)
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--step", "+1")
    assert r.exit_code == 0, r.output
    assert r.output.index("cluster nova-dev-01: scaling") < r.output.index("scaled data,index,query: 4 → 5")
    assert _nodes(fake, cid) == [5]


@pytest.mark.story("CAP-018", "AC5")
def test_step_ac5_no_wait_busy_exit_4(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["scaling", "healthy"])
    write_config(MINIMAL)
    r = run("--auto-approve", "--no-wait", "cluster", "scale", "nova-dev-01", "--step", "+1")
    assert r.exit_code == 4 and "cluster is scaling; try again later" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-018", "AC6")
def test_step_ac6_json_output(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL)
    r = run("--auto-approve", "-o", "json", "cluster", "scale", "nova-dev-01", "--step", "+1")
    assert r.exit_code == 0, r.output
    assert validate_json("scale.schema.json", r.stdout) == {"cluster": "nova-dev-01", "group": "data,index,query",
                                                            "from": 3, "to": 4, "status": "scaled"}
    r = run("--auto-approve", "-o", "json", "cluster", "scale", "nova-dev-01", "--step", "+1", "--max", "4")
    assert validate_json("scale.schema.json", r.stdout)["status"] == "at_limit"
    fake.seed_bucket(cid, "orders", replicas=3)
    r = run("--auto-approve", "-o", "json", "cluster", "scale", "nova-dev-01", "--step", "-1")
    assert r.exit_code == 4 and validate_json("scale.schema.json", r.stdout)["status"] == "blocked"
    fake.clusters[cid]["body"]["serviceGroups"].append(SEARCH)
    write_config(WITH_SEARCH.replace("numOfNodes: 3", "numOfNodes: 4"))
    r = run("--auto-approve", "-o", "json", "cluster", "scale", "nova-dev-01", "--step", "+1", "--all-groups")
    docs = validate_json("scale.schema.json", r.stdout)
    assert [d["status"] for d in docs] == ["scaled", "scaled"]
