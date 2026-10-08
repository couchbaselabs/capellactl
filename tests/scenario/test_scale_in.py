"""CAP-016: scale in safely (capacity checks before nodes or groups are removed)."""
from __future__ import annotations

import pytest

from capellactl.cli import console
from tests.conftest import MINIMAL, seed_healthy

SEARCH = [{"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
           "numOfNodes": 3, "services": ["data", "index", "query"]},
          {"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
           "numOfNodes": 2, "services": ["search"]}]


def _puts(fake):
    return [c for c in fake.writes() if c.method == "PUT"]


@pytest.mark.story("CAP-016", "AC1")
def test_scale_in_ac1_guards_pass_put_sent(fake, run, write_config, monkeypatch):
    _, cid = seed_healthy(fake, nodes=5)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=12288, replicas=1)  # stats: total 20,480, free 8,192
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4"))
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("apply", input="y\n")
    assert r.exit_code == 0, r.output
    assert "  ~ cluster nova-dev-01   scale in\n      serviceGroups[data,index,query].numOfNodes:  5 → 4\n" \
           "      checks: memory ok (12,288 / ~16,384 MB) · replicas ok (max 1, needs 2 data nodes)" in r.output
    assert "Destructive changes:\n  cluster nova-dev-01" in r.output
    [put] = _puts(fake)
    assert put.body["serviceGroups"][0]["numOfNodes"] == 4


@pytest.mark.story("CAP-016", "AC2")
def test_scale_in_ac2_memory_guard_blocks(fake, run, write_config):
    _, cid = seed_healthy(fake, nodes=5)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=18432, replicas=1)  # free 2,048
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4"))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4
    assert ("! cluster nova-dev-01  scale-in blocked: buckets allocate 18,432 MB but data service would have "
            "~16,384 MB after scale-in (5 → 4 nodes)") in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-016", "AC3")
def test_scale_in_ac3_replica_guard_blocks(fake, run, write_config):
    """The story's 4 → 2 example is refused offline (minimum 3 nodes); 3 replicas need 4 data nodes, so 4 → 3."""
    _, cid = seed_healthy(fake, nodes=4)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=1024, replicas=3)
    write_config(MINIMAL)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4
    assert "scale-in blocked: bucket 'orders' has 3 replicas and needs at least 4 data nodes" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-016", "AC4")
def test_scale_in_ac4_group_removal_needs_flags(fake, run, write_config):
    seed_healthy(fake, serviceGroups=SEARCH)
    write_config(MINIMAL)  # the search group is not in the file any more
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4
    assert ("removing serviceGroups[search] removes the last search nodes; pass --allow-service-removal "
            "--allow-service-group-removal") in r.output
    r = run("--auto-approve", "apply", "--allow-service-removal")
    assert r.exit_code == 4 and "pass --allow-service-group-removal" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-016", "AC4")
def test_scale_in_ac4_group_removal_with_flags(fake, run, write_config):
    seed_healthy(fake, serviceGroups=SEARCH)
    write_config(MINIMAL)
    r = run("--auto-approve", "apply", "--allow-service-removal", "--allow-service-group-removal")
    assert r.exit_code == 0, r.output
    [put] = _puts(fake)
    assert [g["services"] for g in put.body["serviceGroups"]] == [["data", "index", "query"]]


@pytest.mark.story("CAP-016", "AC5")
def test_scale_in_ac5_last_data_group_never_removed(fake, run, write_config):
    """Refused before any call, whatever the flags (offline validation); the runtime guard is unit-tested."""
    seed_healthy(fake)
    write_config(MINIMAL.replace("services: [data, index, query]", "services: [index, query]"))
    r = run("--auto-approve", "apply", "--allow-service-removal", "--allow-service-group-removal",
            "--skip-capacity-check")
    assert r.exit_code == 3 and "at least one service group must run the data service" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-016", "AC6")
def test_scale_in_ac6_auto_approve_not_enough_for_group_removal(fake, run, write_config):
    _, cid = seed_healthy(fake, serviceGroups=[*SEARCH, {**SEARCH[1], "services": ["analytics"]}])
    write_config(MINIMAL + "      - node: { compute: { cpu: 4, ram: 16 }, disk: { type: gp3, storage: 50, iops: 3000 } }\n"
                           "        numOfNodes: 2\n        services: [search]\n")
    r = run("--auto-approve", "apply", "--allow-service-removal")  # analytics group removed from the file
    assert r.exit_code == 4, r.output
    assert "removing serviceGroups[analytics] removes the last analytics nodes; pass --allow-service-group-removal" \
        in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-016", "AC7")
def test_scale_in_ac7_stats_unavailable_blocks(fake, run, write_config):
    seed_healthy(fake, nodes=4)
    write_config(MINIMAL)
    fake.fail_next("GET", "*/stats", 403, 1002)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 4
    assert "cannot verify capacity (stats unavailable); pass --skip-capacity-check to proceed at your own risk" \
        in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-016", "AC7")
def test_scale_in_ac7_skip_capacity_check(fake, run, write_config):
    seed_healthy(fake, nodes=4)
    write_config(MINIMAL)
    fake.fail_next("GET", "*/stats", 403, 1002)
    r = run("--auto-approve", "apply", "--skip-capacity-check")
    assert r.exit_code == 0, r.output
    assert "checks: memory not checked (--skip-capacity-check) · replicas ok" in r.output
    assert len(_puts(fake)) == 1


@pytest.mark.story("CAP-016", "AC8")
def test_scale_in_ac8_rerun_zero_writes_no_stats_call(fake, run, write_config):
    seed_healthy(fake, nodes=4)
    write_config(MINIMAL)
    assert run("--auto-approve", "apply").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert "No changes" in r.output and fake.writes() == [] and fake.calls("GET", "*/stats") == []
