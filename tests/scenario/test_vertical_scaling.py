"""CAP-017: vertical scaling (compute and disk). AC6 (memory guard on RAM decrease) waits for CAP-016."""
from __future__ import annotations

import pytest

from capellactl.config.loader import ConfigError, load_config
from capellactl.resources.cluster import service_group_changes
from tests.conftest import MINIMAL, seed_healthy


@pytest.mark.story("CAP-017", "AC1")
def test_vertical_ac1_compute_change_body(fake, run, write_config):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL.replace("compute: { cpu: 4, ram: 16 }", "compute: { cpu: 8, ram: 32 }"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "scale up" in r.output
    g = fake.calls("PUT", f"*/clusters/{cid}")[0].body["serviceGroups"][0]
    assert g["node"]["compute"] == {"cpu": 8, "ram": 32} and g["numOfNodes"] == 3
    assert g["node"]["disk"] == {"type": "gp3", "storage": 50, "iops": 3000}


@pytest.mark.story("CAP-017", "AC1")
def test_scaling_classify_ac1_vertical():
    g = {"node": {"compute": {"cpu": 4, "ram": 16}}, "numOfNodes": 3, "services": ["data"]}
    _, blocked, labels = service_group_changes(
        {"serviceGroups": [{**g, "node": {"compute": {"cpu": 8, "ram": 32}}}]}, {"serviceGroups": [g]})
    assert blocked == [] and labels == {"scale up"}


@pytest.mark.story("CAP-017", "AC2")
@pytest.mark.parametrize("provider,region,disk_before,disk_after", [
    ("aws", "us-east-1", {"type": "gp3", "storage": 50, "iops": 3000}, {"type": "gp3", "storage": 100, "iops": 6000}),
    ("azure", "eastus", {"type": "P10"}, {"type": "P20"}),
    ("gcp", "us-east1", {"type": "pd-ssd", "storage": 50}, {"type": "pd-ssd", "storage": 200}),
])
def test_vertical_ac2_disk_change_by_provider(fake, run, write_config, provider, region, disk_before, disk_after):
    groups = [{"node": {"compute": {"cpu": 4, "ram": 16}, "disk": disk_before}, "numOfNodes": 3,
               "services": ["data", "index", "query"]}]
    _, cid = seed_healthy(fake, serviceGroups=groups,
                          cloudProvider={"type": provider, "region": region, "cidr": "10.10.0.0/24"})
    flow = ", ".join(f"{k}: {v}" for k, v in disk_after.items())
    text = (MINIMAL.replace("type: aws, region: us-east-1", f"type: {provider}, region: {region}")
            .replace("disk: { type: gp3, storage: 50, iops: 3000 }", f"disk: {{ {flow} }}"))
    write_config(text)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert fake.calls("PUT", f"*/clusters/{cid}")[0].body["serviceGroups"][0]["node"]["disk"] == disk_after


@pytest.mark.story("CAP-017", "AC3")
def test_vertical_ac3_disk_shrink_blocked(fake, run, write_config):
    groups = [{"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 100, "iops": 3000}},
               "numOfNodes": 3, "services": ["data", "index", "query"]}]
    seed_healthy(fake, serviceGroups=groups)
    write_config()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4
    assert "node.disk.storage: 100 → 50 GB  disk size cannot be reduced" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-017", "AC4")
def test_vertical_validate_ac4_disk_type_provider(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL.replace("type: gp3", "type: P20"))
    with pytest.raises(ConfigError, match="disk type P20 is not valid for aws"):
        load_config(p, env={"CAPELLA_ORG_ID": "o"})


@pytest.mark.story("CAP-017", "AC5")
def test_vertical_ac5_combined_single_put(fake, run, write_config):
    groups = [{"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
               "numOfNodes": 3, "services": ["data", "index", "query"]},
              {"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
               "numOfNodes": 2, "services": ["search"]}]
    _, cid = seed_healthy(fake, serviceGroups=groups)
    write_config(MINIMAL.replace("compute: { cpu: 4, ram: 16 }", "compute: { cpu: 8, ram: 32 }")
                 .replace("        services: [data, index, query]\n", """        services: [data, index, query]
      - node:
          compute: { cpu: 4, ram: 16 }
          disk: { type: gp3, storage: 50, iops: 3000 }
        numOfNodes: 4
        services: [search]
"""))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "scale out / scale up" in r.output
    assert len(fake.calls("PUT", f"*/clusters/{cid}")) == 1


@pytest.mark.story("CAP-017", "AC7")
def test_vertical_ac7_rerun_zero_writes(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL.replace("compute: { cpu: 4, ram: 16 }", "compute: { cpu: 8, ram: 32 }"))
    assert run("--auto-approve", "apply").exit_code == 0
    fake.reset_calls()
    assert run("--auto-approve", "apply").exit_code == 0 and fake.writes() == []


@pytest.mark.story("CAP-017", "AC6")
def test_vertical_ac6_ram_decrease_memory_guard(fake, run, write_config):
    """32 → 16 GB per data node halves the data service: projected = total × 16 / 32."""
    groups = [{"node": {"compute": {"cpu": 8, "ram": 32}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
               "numOfNodes": 3, "services": ["data", "index", "query"]}]
    _, cid = seed_healthy(fake, serviceGroups=groups)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=12288, replicas=1)  # total 20,480 → ~10,240 after
    write_config()  # MINIMAL: 4 vCPU / 16 GB
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4, r.output
    assert "buckets allocate 12,288 MB but data service would have ~10,240 MB after scale-in (32 → 16 GB per node)" \
        in r.output
    assert fake.writes() == []
    fake.buckets[(cid, next(k for c, k in fake.buckets if c == cid))]["memoryAllocationInMb"] = 8192
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0 and "checks: memory ok (8,192 / ~10,240 MB)" in r.output, r.output
