"""CAP-056: cluster backup schedule (cloud snapshots) as code."""
from __future__ import annotations

import json

import pytest

from tests.conftest import file_clusters, seed_healthy

NO_CHANGES = "Plan: 0 to add, 0 to change, 0 to delete, 0 blocked."
SCHEDULE = {"interval": 24, "retention": 720, "startTime": "2026-10-30T02:00:00Z", "copyToRegions": ["us-west-2"]}


@pytest.fixture
def imported(fake, run, tmp_path):
    pid, cid = seed_healthy(fake)
    assert run("import").exit_code == 0
    fake.reset_calls()
    return tmp_path / "capella.yaml", cid


def _schedule(path):
    return file_clusters(path)[0].get("backupSchedule")


@pytest.mark.story("CAP-056", "AC1")
def test_cluster_backup_ac1_set_body(fake, run, imported):
    path, cid = imported
    r = run("--auto-approve", "cluster", "backup", "schedule", "set", "nova-dev-01", "--every", "24", "--retain", "30d")
    assert r.exit_code == 0, r.output
    assert "+ backup-schedule nova-dev-01  every 24 h · kept 30 days" in r.output
    assert fake.calls("GET", "*/cloudsnapshotbackupschedule/options")  # what the plan permits is read first
    puts = fake.calls("PUT", "*/cloudsnapshotbackupschedule")
    assert len(puts) == 1 and puts[0].body == {"interval": 24, "retention": 720, "copyToRegions": []}
    assert _schedule(path) == {"interval": 24, "retention": 720}
    assert fake.snapshot_schedules[cid]["retention"] == 720


@pytest.mark.story("CAP-056", "AC1")
def test_cluster_backup_ac1_no_drift(fake, run, imported):
    path, _ = imported
    r = run("--auto-approve", "cluster", "backup", "schedule", "set", "nova-dev-01", "--every", "6", "--retain", "168h",
            "--start", "02:00", "--copy-to", "us-west-2")
    assert r.exit_code == 0, r.output
    body = fake.calls("PUT", "*/cloudsnapshotbackupschedule")[0].body
    assert body["startTime"].endswith("T02:00:00Z") and body["copyToRegions"] == ["us-west-2"]
    assert _schedule(path) == {"interval": 6, "retention": 168, "startTime": "02:00", "copyToRegions": ["us-west-2"]}
    assert NO_CHANGES in run("plan").output
    assert run("drift", "--detailed-exitcode").exit_code == 0


@pytest.mark.story("CAP-056", "AC2")
def test_cluster_backup_ac2_rerun_zero_writes(fake, run, imported):
    args = ("--auto-approve", "cluster", "backup", "schedule", "set", "nova-dev-01", "--every", "24", "--retain", "30d",
            "--start", "02:00")
    assert run(*args).exit_code == 0
    fake.reset_calls()
    r = run(*args)
    assert r.exit_code == 0 and "already matches" in r.output
    assert "No changes" in run("--auto-approve", "apply").output
    assert fake.writes() == []


@pytest.mark.story("CAP-056", "AC3")
@pytest.mark.parametrize("extra,message", [
    (["--every", "3", "--retain", "30d"], "interval 3 is not permitted: use one of 1, 2, 4, 6, 8, 12, 24 hours"),
    (["--every", "24", "--retain", "12"], "retention 12 h is not permitted: keep backups 1 day to 90 days"),
    (["--every", "24", "--retain", "120d"], "retention 120 days is not permitted"),
    (["--every", "24", "--retain", "30d", "--copy-to", "us-east-2", "--copy-to", "us-west-2", "--copy-to",
      "eu-west-1"], "copyToRegions takes at most two regions"),
    (["--every", "24", "--retain", "30d", "--copy-to", "mars-1"], "copies cannot go to mars-1"),
    (["--every", "24", "--retain", "1w"], "--retain takes hours or days"),
    (["--retain", "30d"], "a new backup schedule needs --every HOURS and --retain DURATION"),
])
def test_cluster_backup_ac3_refused(fake, run, imported, extra, message):
    path, _ = imported
    before = path.read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "backup", "schedule", "set", "nova-dev-01", *extra)
    assert r.exit_code == 3 and message in r.output, r.output
    assert fake.writes() == [] and path.read_text(encoding="utf-8") == before


@pytest.mark.story("CAP-056", "AC3")
def test_cluster_backup_ac3_free_tier(fake, run, tmp_path):
    pid = fake.seed_project("nova-dev")
    fake.seed_free_cluster(pid, "try-01")
    assert run("import").exit_code == 0
    r = run("--auto-approve", "cluster", "backup", "schedule", "set", "try-01", "--every", "24", "--retain", "30d")
    assert r.exit_code == 4 and "free-tier clusters have no backups" in r.output
    r = run("cluster", "backup", "list", "try-01")
    assert r.exit_code == 4 and "free-tier clusters have no backups" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-056", "AC4")
def test_cluster_backup_ac4_show(fake, run, imported):
    _, cid = imported
    r = run("cluster", "backup", "schedule", "show", "nova-dev-01")
    assert r.exit_code == 0 and "has no backup schedule" in r.output
    fake.snapshot_schedules[cid] = dict(SCHEDULE)
    r = run("cluster", "backup", "schedule", "show", "nova-dev-01")
    assert r.exit_code == 0, r.output
    assert "every 24 h · kept 30 days · first at 02:00 UTC · copies: us-west-2" in r.output
    assert "next backup: " in r.output
    data = json.loads(run("-o", "json", "cluster", "backup", "schedule", "show", "nova-dev-01").output)
    assert data["interval"] == 24 and data["copyToRegions"] == ["us-west-2"] and "nextBackup" in data


@pytest.mark.story("CAP-056", "AC4")
def test_cluster_backup_ac4_options(fake, run, imported):
    r = run("cluster", "backup", "schedule", "options", "nova-dev-01")
    assert r.exit_code == 0, r.output
    assert "every (hours)   1, 2, 4, 6, 8, 12, 24" in r.output
    assert "keep            1 day to 90 days" in r.output
    assert "copy regions    us-east-2, us-west-2, eu-west-1 (up to two)" in r.output
    data = json.loads(run("-o", "json", "cluster", "backup", "schedule", "options", "nova-dev-01").output)
    assert data["maximumRetention"] == 2160 and data["regions"][0] == "us-east-2"
    assert fake.writes() == []


@pytest.mark.story("CAP-056", "AC5")
def test_cluster_backup_ac5_delete(fake, run, imported):
    path, cid = imported
    assert run("--auto-approve", "cluster", "backup", "schedule", "set", "nova-dev-01", "--every", "24", "--retain",
               "30d").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "backup", "schedule", "delete", "nova-dev-01")
    assert r.exit_code == 0, r.output
    assert "- backup schedule nova-dev-01  every 24 h · kept 30 days" in r.output
    assert len(fake.calls("DELETE", "*/cloudsnapshotbackupschedule")) == 1
    assert cid not in fake.snapshot_schedules and _schedule(path) is None


@pytest.mark.story("CAP-056", "AC5")
def test_cluster_backup_ac5_delete_missing_noop(fake, run, imported):
    r = run("--auto-approve", "cluster", "backup", "schedule", "delete", "nova-dev-01")
    assert r.exit_code == 0 and "has no backup schedule; nothing to do" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-056", "AC6")
def test_cluster_backup_ac6_apply_creates(fake, run, imported):
    path, cid = imported
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    at = next(i for i, line in enumerate(lines) if line.lstrip().startswith("serviceGroups:"))
    indent = lines[at][: len(lines[at]) - len(lines[at].lstrip())]
    lines.insert(at, f"{indent}backupSchedule: {{interval: 12, retention: 336}}\n")
    path.write_text("".join(lines), encoding="utf-8")
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert fake.snapshot_schedules[cid] == {"interval": 12, "retention": 336, "copyToRegions": []}
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output and fake.writes() == []


@pytest.mark.story("CAP-056", "AC6")
def test_cluster_backup_ac6_sync_round_trip(fake, run, imported):
    path, cid = imported
    fake.snapshot_schedules[cid] = dict(SCHEDULE)
    r = run("sync")
    assert r.exit_code == 0, r.output
    assert _schedule(path) == {"interval": 24, "retention": 720, "startTime": "02:00", "copyToRegions": ["us-west-2"]}
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output and fake.writes() == []


@pytest.mark.story("CAP-056", "AC6")
def test_cluster_backup_ac6_sync_keeps_schedule_the_key_cannot_read(fake, run, imported):
    """A Project Manager key may not read backups: sync keeps the file's schedule and warns once."""
    path, cid = imported
    assert run("--auto-approve", "cluster", "backup", "schedule", "set", "nova-dev-01", "--every", "24", "--retain",
               "30d").exit_code == 0
    fake.fail_next("GET", "*/cloudsnapshotbackupschedule", 403, times=5)
    r = run("sync")
    assert r.exit_code == 0, r.output
    assert "[WARNING]: backup schedules not read: the API key does not have the Organization Owner or Project Owner role" in r.output
    assert _schedule(path) == {"interval": 24, "retention": 720}


@pytest.mark.story("CAP-056", "AC6")
def test_cluster_backup_ac6_drift_and_prune(fake, run, imported):
    _, cid = imported
    fake.snapshot_schedules[cid] = dict(SCHEDULE)
    r = run("plan")
    assert NO_CHANGES in r.output and "backup-schedule" not in r.output  # without the key, plan leaves it alone
    r = run("drift")
    assert "backup-schedule nova-dev-01  every 24 h · kept 30 days" in r.output, r.output
    r = run("--auto-approve", "apply", "--prune")
    assert r.exit_code == 0, r.output
    assert "- backup-schedule nova-dev-01" in r.output and cid not in fake.snapshot_schedules


@pytest.mark.story("CAP-056", "AC7")
def test_cluster_backup_ac7_help(run):
    for verb in ("show", "options", "set", "delete"):
        r = run("cluster", "backup", "schedule", verb, "--help")
        assert r.exit_code == 0 and "Examples:" in r.output and "capellactl cluster backup schedule" in r.output, verb
    r = run("help", "backup")
    assert "Cluster backup" in r.output and "Bucket backup" in r.output and "backupSchedule" in r.output
    r = run("help", "config", "clusters.backupSchedule")
    assert r.exit_code == 0 and "Cloud snapshot backups" in r.output
