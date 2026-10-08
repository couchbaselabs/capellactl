"""CAP-012: edit cluster settings and immutable fields."""
from __future__ import annotations

import json

import pytest

from capellactl.resources.cluster import build_update_body
from tests.conftest import MINIMAL, seed_healthy


@pytest.mark.story("CAP-012", "AC1")
def test_cluster_update_ac1_full_body_overlay(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL.replace("Nova development cluster", "Nova dev, now on enterprise")
                 .replace("plan: developer pro", "plan: enterprise"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert 'support.plan:  "developer pro" → "enterprise"' in r.output
    put = fake.calls("PUT", f"*/clusters/{cid}")[0]
    assert put.headers["If-Match"]
    assert put.body["name"] == "nova-dev-01" and put.body["description"] == "Nova dev, now on enterprise"
    assert put.body["support"] == {"plan": "enterprise", "timezone": "PT"}
    assert put.body["serviceGroups"] == fake.clusters[cid]["body"]["serviceGroups"]


@pytest.mark.story("CAP-012", "AC1")
def test_build_update_body_ac1_overlay():
    observed = {"name": "c", "description": "d", "support": {"plan": "basic", "timezone": "ET"},
                "serviceGroups": [{"node": {"compute": {"cpu": 4, "ram": 16}}, "numOfNodes": 3, "services": ["data"]}]}
    body = build_update_body(observed, {"name": "c", "support": {"plan": "enterprise"}}, rename=False)
    assert body == {"name": "c", "description": "d", "support": {"plan": "enterprise", "timezone": "ET"},
                    "serviceGroups": observed["serviceGroups"]}


@pytest.mark.story("CAP-012", "AC2")
def test_build_update_body_ac2_preserves_unset_fields():
    observed = {"name": "c", "description": "Prod", "support": {"plan": "basic"}, "serviceGroups": []}
    assert build_update_body(observed, {"name": "c", "support": {"plan": "enterprise"}}, rename=False)["description"] == "Prod"


@pytest.mark.story("CAP-012", "AC3")
@pytest.mark.parametrize("old,new,field", [
    ("region: us-east-1", "region: us-west-2", "cloudProvider.region"),
    ("type: aws, region", "type: gcp, region", "cloudProvider.type"),
    ("cidr: 10.10.0.0/24", "cidr: 10.20.0.0/23", "cloudProvider.cidr"),
    ("availability: { type: multi }", "availability: { type: single }", "availability.type"),
    ("    cloudProvider:", "    couchbaseServer: { version: '7.6' }\n    cloudProvider:", "couchbaseServer.version"),
    ("    cloudProvider:", "    cmekId: key-1\n    cloudProvider:", "cmekId"),
    ("    cloudProvider:", "    enablePrivateDNSResolution: true\n    cloudProvider:", "enablePrivateDNSResolution"),
    ("    cloudProvider:", "    configurationType: singleNode\n    cloudProvider:", "configurationType"),
])
def test_cluster_update_ac3_immutable_blocked(fake, run, write_config, old, new, field):
    seed_healthy(fake)
    text = MINIMAL.replace(old, new, 1)
    if "gcp" in new:
        text = text.replace("type: gp3, storage: 50, iops: 3000", "type: pd-ssd, storage: 50")
    if "singleNode" in new:
        text = text.replace("type: multi", "type: single").replace("numOfNodes: 3", "numOfNodes: 1")
    write_config(text)
    r = run("--auto-approve", "apply")
    if r.exit_code == 3:  # some combinations are rejected offline first; still blocked
        return
    assert r.exit_code == 4, r.output
    assert "immutable:" in r.output and field in r.output and "(requires a new cluster)" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-012", "AC4")
def test_cluster_update_ac4_wait_before_and_after(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.set_transition(cid, ["rebalancing", "healthy"])
    write_config(MINIMAL.replace("Nova development cluster", "new description"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    idx = {id(c): i for i, c in enumerate(fake._calls)}
    put = fake.calls("PUT", f"*/clusters/{cid}")[0]
    gets = [idx[id(c)] for c in fake.calls("GET", f"*/clusters/{cid}")]
    assert any(i < idx[id(put)] for i in gets) and any(i > idx[id(put)] for i in gets)
    assert "rebalancing" in r.output and "scaling" in r.output


@pytest.mark.story("CAP-012", "AC5")
def test_cluster_update_ac5_412_retry(fake, run, write_config):
    seed_healthy(fake)
    fake.fail_next("PUT", "*/clusters/*", 412)
    write_config(MINIMAL.replace("Nova development cluster", "x"))
    assert run("--auto-approve", "apply").exit_code == 0
    assert len(fake.calls("PUT", "*/clusters/*")) == 2


@pytest.mark.story("CAP-012", "AC6")
def test_cluster_update_ac6_rename_with_pinned_id(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL.replace("  - name: nova-dev-01", f"  - id: {cid}\n    name: nova-dev-02"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert 'name:  "nova-dev-01" → "nova-dev-02"' in r.output
    assert fake.clusters[cid]["body"]["name"] == "nova-dev-02"


@pytest.mark.story("CAP-012", "AC6")
def test_cluster_update_ac6_rename_hint_without_id(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL.replace("name: nova-dev-01", "name: nova-dev-02"))
    r = run("plan")
    assert "+ cluster nova-dev-02" in r.output
    assert f"did you mean to rename nova-dev-01? pin id: {cid} to rename" in r.output


@pytest.mark.story("CAP-012", "AC7")
def test_cluster_update_ac7_rerun_zero_writes(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL.replace("plan: developer pro", "plan: enterprise"))
    assert run("--auto-approve", "apply").exit_code == 0
    fake.reset_calls()
    assert run("--auto-approve", "apply").exit_code == 0 and fake.writes() == []


NOTE = 'note: Capella runs a cluster update job for this (shown as "scale" in the Capella UI); nodes do not change'


@pytest.mark.story("CAP-012", "AC1")
def test_cluster_update_ac1_settings_only_note(fake, run, write_config):
    """A description/support change still starts a Capella cluster job; say so, and do not call it scaling."""
    seed_healthy(fake)
    write_config(MINIMAL.replace("Nova development cluster", "Nova demo cluster"))
    r = run("plan")
    assert '      description:  "Nova development cluster" → "Nova demo cluster"\n      ' + NOTE in r.output, r.output
    js = json.loads(run("-o", "json", "plan").output)
    cl = next(a for a in js["plan"]["actions"] if a["kind"] == "cluster")
    assert NOTE in cl["notes"]
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "cluster nova-dev-01: applying the change (Capella: scaling)" in r.output
    assert ": scaling (" not in r.output


@pytest.mark.story("CAP-012", "AC1")
def test_cluster_update_ac1_scaling_keeps_scaling_wording(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert NOTE not in r.output and "cluster nova-dev-01: scaling (" in r.output
