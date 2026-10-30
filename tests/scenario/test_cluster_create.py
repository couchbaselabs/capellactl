"""CAP-011: create cluster."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from capellactl.config.loader import ConfigError, load_config
from tests.conftest import EXAMPLE, MINIMAL, seed_healthy
from tests.scenario.helpers import FULL

FIXTURE = Path(__file__).parent / "fixtures" / "cluster_create_body.json"


def _example(tmp_path):
    shutil.copy(EXAMPLE, tmp_path / "capella.yaml")
    (tmp_path / "secrets").mkdir(exist_ok=True)
    (tmp_path / "secrets" / "reporting_ro.txt").write_text("R3port!ng-pw", encoding="utf-8")
    return {"ORDERS_APP_PASSWORD": "Orders#App-123"}


@pytest.mark.story("CAP-011", "AC1")
def test_cluster_ac1_create_body_matches_fixture(fake, run, tmp_path):
    env = _example(tmp_path)
    fake.seed_project("nova-dev", description="Nova development environment")
    r = run("--auto-approve", "apply", extra_env=env)
    assert r.exit_code == 0, r.output
    post = fake.calls("POST", "*/clusters")[0]
    assert post.body == json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.story("CAP-011", "AC1")
def test_cluster_ac1_plan_line_summary(fake, run, write_config):
    fake.seed_project("nova-dev", description="Nova development environment")
    write_config()
    r = run("plan")
    assert "+ cluster nova-dev-01  aws us-east-1 · multi-AZ · 3 × 4 vCPU/16 GB · data,index,query · developer pro" in r.output


@pytest.mark.story("CAP-011", "AC2")
def test_cluster_ac2_children_after_healthy(fake, run, write_config, stub_tree):
    fake.seed_project("nova-dev", description="Nova development environment")
    write_config(FULL)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    calls = fake._calls
    post_cluster = next(i for i, c in enumerate(calls) if c.method == "POST" and c.path.endswith("/clusters"))
    first_child = next(i for i, c in enumerate(calls) if c.method == "POST" and c.path.endswith("/allowedcidrs"))
    cid = next(iter(fake.clusters))
    polls = [i for i, c in enumerate(calls) if c.method == "GET" and c.path.endswith(f"/clusters/{cid}")
             and post_cluster < i < first_child]
    assert polls, "children must not be created before the cluster is polled to healthy"
    assert r.output.index("cluster nova-dev-01: healthy") < r.output.index("creating allowed-cidr")


@pytest.mark.story("CAP-011", "AC2")
def test_cluster_ac2_summary_connection_string(fake, run, write_config):
    write_config()
    r = run("--auto-approve", "apply")
    assert "connectionString (nova-dev-01): couchbases://cb." in r.output


@pytest.mark.story("CAP-011", "AC3")
def test_cluster_ac3_existing_matches_noop(fake, run, write_config):
    seed_healthy(fake)
    write_config()
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0 and "= cluster nova-dev-01" in r.output


@pytest.mark.story("CAP-011", "AC3")
def test_cluster_ac3_deploying_waits_no_post(fake, run, write_config, stub_tree):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["deploying", "healthy"])
    write_config(FULL)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert not fake.calls("POST", "*/clusters")
    assert "cluster nova-dev-01: deploying" in r.output


@pytest.mark.story("CAP-011", "AC4")
def test_cluster_ac4_deployment_failed_blocked(fake, run, write_config):
    seed_healthy(fake, )
    cid = next(iter(fake.clusters))
    fake.clusters[cid]["seq"] = [("deploymentFailed", -1.0)]
    write_config()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4
    assert ("! cluster nova-dev-01  in deploymentFailed; delete it (capellactl cluster delete nova-dev-01) "
            "and re-run apply") in r.output
    assert fake.writes() == []


CREATE_RULES = [
    ("services: [data, index, query]", "services: [index]", "at least one service group must run the data service"),
    ("    cloudProvider:", "    configurationType: singleNode\n    cloudProvider:", "singleNode clusters must use availability: single"),
    ("    cloudProvider:", "    configurationType: singleNode\n    cloudProvider:", "singleNode clusters have exactly 1 node"),
    ("type: gp3", "type: pd-ssd", "disk type pd-ssd is not valid for aws"),
    ("storage: 50", "storage: 20", "must be between 50"),
    ("    availability: { type: multi }", "    availability: { type: multi }\n    zones: [a, b]", "zones"),
    ("    availability: { type: multi }", "    availability: { type: multi }\n    zones: [use1-az1]",
     "zones can only be set for availability: single"),
]


@pytest.mark.story("CAP-011", "AC5")
@pytest.mark.parametrize("old,new,msg", CREATE_RULES)
def test_cluster_validate_ac5_rules(tmp_path, old, new, msg):
    p = tmp_path / "c.yaml"
    assert old in MINIMAL
    p.write_text(MINIMAL.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(p, env={"CAPELLA_ORG_ID": "o"})
    assert msg in str(ei.value) or (msg == "must be between 50" and "must be >= 50" in str(ei.value))


@pytest.mark.story("CAP-011", "AC6")
def test_cluster_ac6_422_message_and_hint(fake, run, write_config):
    fake.seed_project("nova-dev", description="Nova development environment")
    fake.fail_next("POST", "*/clusters", 422, code=4005)
    write_config()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 1
    assert "[ERROR]: Failed: cluster nova-dev-01" in r.output and "[ACTION]: injected 422." in r.output
    assert len(fake.writes()) == 1


@pytest.mark.story("CAP-011", "AC7")
def test_cluster_ac7_rerun_zero_writes(fake, run, write_config):
    write_config()
    assert run("--auto-approve", "apply").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0 and fake.writes() == []
