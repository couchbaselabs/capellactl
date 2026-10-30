"""CAP-015: scale out (declarative and imperative)."""
from __future__ import annotations

import copy

import pytest

from capellactl.config.loader import ConfigError, load_config
from capellactl.resources.cluster import service_group_changes
from tests.conftest import MINIMAL, seed_healthy

SEARCH = """\
      - node:
          compute: { cpu: 4, ram: 16 }
          disk: { type: gp3, storage: 50, iops: 3000 }
        numOfNodes: 2
        services: [search]
"""


@pytest.mark.story("CAP-015", "AC1")
def test_scale_out_ac1_add_nodes_body(fake, run, write_config):
    _, cid = seed_healthy(fake)
    before = copy.deepcopy(fake.clusters[cid]["body"]["serviceGroups"])
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 5"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "~ cluster nova-dev-01   scale out" in r.output
    expected = copy.deepcopy(before)
    expected[0]["numOfNodes"] = 5
    assert fake.calls("PUT", f"*/clusters/{cid}")[0].body["serviceGroups"] == expected
    assert "cluster nova-dev-01: healthy" in r.output


@pytest.mark.story("CAP-015", "AC1")
def test_scaling_classify_ac1_out_nodes():
    g = {"node": {"compute": {"cpu": 4, "ram": 16}}, "numOfNodes": 3, "services": ["data"]}
    changes, blocked, labels = service_group_changes({"serviceGroups": [{**g, "numOfNodes": 4}]}, {"serviceGroups": [g]})
    assert [(c.path, c.before, c.after) for c in changes] == [("serviceGroups[data].numOfNodes", 3, 4)]
    assert blocked == [] and labels == {"scale out"}


@pytest.mark.story("CAP-015", "AC2")
def test_scale_out_ac2_add_group_body(fake, run, write_config):
    _, cid = seed_healthy(fake)
    existing = copy.deepcopy(fake.clusters[cid]["body"]["serviceGroups"])
    write_config(MINIMAL.replace("        services: [data, index, query]\n",
                                 "        services: [data, index, query]\n" + SEARCH))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "    + serviceGroups[search]  2 × 4 vCPU/16 GB gp3 50 GB" in r.output
    body = fake.calls("PUT", f"*/clusters/{cid}")[0].body["serviceGroups"]
    assert body[0] == existing[0]
    assert body[1]["services"] == ["search"] and body[1]["numOfNodes"] == 2


@pytest.mark.story("CAP-015", "AC2")
def test_scaling_classify_ac2_out_group():
    g = {"numOfNodes": 3, "services": ["data"]}
    s = {"numOfNodes": 2, "services": ["search"]}
    _, blocked, labels = service_group_changes({"serviceGroups": [g, s]}, {"serviceGroups": [g]})
    assert blocked == [] and labels == {"scale out"}


@pytest.mark.story("CAP-015", "AC3")
def test_scaling_classify_ac3_order_insensitive():
    g = {"node": {"compute": {"cpu": 4, "ram": 16}}, "numOfNodes": 3, "services": ["data", "index"]}
    s = {"node": {"compute": {"cpu": 4, "ram": 16}}, "numOfNodes": 2, "services": ["search"]}
    desired = {"serviceGroups": [{**s}, {**g, "services": ["index", "data"], "numOfNodes": 4}]}
    changes, _, labels = service_group_changes(desired, {"serviceGroups": [g, s]})
    assert [c.path for c in changes] == ["serviceGroups[data,index].numOfNodes"] and labels == {"scale out"}


@pytest.mark.story("CAP-015", "AC4")
@pytest.mark.parametrize("text,msg", [
    (MINIMAL.replace("        services: [data, index, query]\n", "        services: [data, index, query]\n"
                     + SEARCH.replace("numOfNodes: 2", "numOfNodes: 25")), "additional service groups allow 2–24 nodes"),
    (MINIMAL.replace("numOfNodes: 3", "numOfNodes: 28"), "must be between 1 and 27"),
    (MINIMAL.replace("    cloudProvider:", "    configurationType: singleNode\n    cloudProvider:")
     .replace("type: multi", "type: single").replace("numOfNodes: 3", "numOfNodes: 2"),
     "singleNode clusters have exactly 1 node; create a multiNode cluster to scale out"),
])
def test_scale_out_validate_ac4_limits(tmp_path, text, msg):
    p = tmp_path / "c.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(p, env={"CAPELLA_ORG_ID": "o"})
    assert msg in str(ei.value)


@pytest.mark.story("CAP-015", "AC5")
def test_scale_cli_ac5_nodes_defaults_to_data_group(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config()
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "5")
    assert r.exit_code == 0, r.output
    assert "serviceGroups[data,index,query].numOfNodes:  3 → 5" in r.output
    assert fake.clusters[cid]["body"]["serviceGroups"][0]["numOfNodes"] == 5


@pytest.mark.story("CAP-015", "AC5")
def test_scale_cli_ac5_ambiguous_group(fake, run, write_config):
    groups = [{"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
               "numOfNodes": 3, "services": ["data"]},
              {"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
               "numOfNodes": 2, "services": ["data", "search"]}]
    seed_healthy(fake, serviceGroups=groups)
    run("import")
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "4")
    assert r.exit_code == 3 and "[ERROR]: more than one group runs data\n[ACTION]: Name the group by its services with --group SERVICES" in r.output
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "4", "--group", "search,data")
    assert r.exit_code == 0, r.output


@pytest.mark.story("CAP-015", "AC6")
def test_scale_cli_ac6_file_updated_no_drift(fake, run, write_config, tmp_path):
    seed_healthy(fake)
    write_config()
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "5")
    assert r.exit_code == 0, r.output
    assert "numOfNodes: 5" in (tmp_path / "capella.yaml").read_text(encoding="utf-8")
    fake.reset_calls()
    assert run("plan", "--detailed-exitcode").exit_code == 0 and fake.writes() == []


@pytest.mark.story("CAP-015", "AC7")
def test_scale_out_ac7_turned_off_blocked(fake, run, write_config):
    _, cid = seed_healthy(fake)
    fake.clusters[cid]["seq"] = [("turnedOff", -1.0)]
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4
    assert "! cluster nova-dev-01  turned off; power it on before scaling" in r.output


@pytest.mark.story("CAP-015", "AC7")
def test_scale_out_ac7_scale_failed(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4"))
    sent: list[bool] = []

    def fail_after_put(method: str, path: str) -> None:
        if method == "PUT":
            sent.append(True)
        elif sent and method == "GET" and path.endswith(cid) and len(sent) == 1:
            fake.set_transition(cid, ["scaleFailed"])
            sent.append(True)

    fake.hooks.append(fail_after_put)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 1
    assert "cluster nova-dev-01 entered scaleFailed; check the Capella UI activity log" in r.output


@pytest.mark.story("CAP-015", "AC8")
def test_scale_out_ac8_rerun_zero_writes(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 5"))
    assert run("--auto-approve", "apply").exit_code == 0
    fake.reset_calls()
    assert run("--auto-approve", "apply").exit_code == 0 and fake.writes() == []


@pytest.mark.story("CAP-015", "AC8")
def test_scale_cli_ac8_same_count_noop(fake, run, write_config):
    seed_healthy(fake, nodes=5)
    write_config()
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "5")
    assert r.exit_code == 0 and "already at 5 nodes" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-016", "AC1")
def test_scale_cli_scale_in_runs_guards(fake, run, write_config):
    """Since CAP-016, `cluster scale` to fewer nodes is applied when the capacity checks pass."""
    _, cid = seed_healthy(fake, nodes=5)
    write_config()
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "3")
    assert r.exit_code == 0, r.output
    assert "scale in" in r.output and "checks: memory ok" in r.output and "replicas ok" in r.output
    assert fake.clusters[cid]["body"]["serviceGroups"][0]["numOfNodes"] == 3
