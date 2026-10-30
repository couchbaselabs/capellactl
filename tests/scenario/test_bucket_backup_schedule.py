"""CAP-058: bucket backup schedule as code, and backup cycles."""
from __future__ import annotations

import json

import pytest

from capellactl.cli import console
from tests.conftest import file_clusters, seed_healthy
from tests.fakes.capella import bucket_id

DEFAULTS = {"dayOfWeek": "sunday", "startAt": 0, "incrementalEvery": 24, "retentionTime": "30days",
            "costOptimizedRetention": False}
NO_CHANGES = "Plan: 0 to add, 0 to change, 0 to delete, 0 blocked."


@pytest.fixture
def imported(fake, run, tmp_path):
    pid, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders")
    assert run("import").exit_code == 0
    fake.reset_calls()
    return tmp_path / "capella.yaml", cid


def _schedule(path):
    return next(b for b in file_clusters(path)[0]["buckets"] if b["name"] == "orders").get("backupSchedule")


def _set(run, *extra):
    return run("--auto-approve", "bucket", "backup", "schedule", "set", "nova-dev-01", "orders", *extra)


@pytest.mark.story("CAP-058", "AC1")
def test_bucket_backup_ac1_set_create(fake, run, imported):
    path, cid = imported
    r = _set(run)
    assert r.exit_code == 0, r.output
    assert ("+ bucket-backup-schedule nova-dev-01/orders  weekly full on sunday at 00:00 UTC · incremental every 24 h · "
            "kept 30 days") in r.output
    posts = fake.calls("POST", "*/backup/schedules")
    assert len(posts) == 1 and posts[0].body == {"type": "weekly", "weeklySchedule": DEFAULTS}
    assert _schedule(path) == DEFAULTS
    assert list(next(b for b in file_clusters(path)[0]["buckets"]))[-1] == "backupSchedule"
    assert NO_CHANGES in run("plan").output


@pytest.mark.story("CAP-058", "AC1")
def test_bucket_backup_ac1_set_update(fake, run, imported):
    path, cid = imported
    assert _set(run).exit_code == 0
    fake.reset_calls()
    r = _set(run, "--incremental-every", "12")
    assert r.exit_code == 0, r.output
    assert "incrementalEvery:  24 → 12" in r.output
    puts = fake.calls("PUT", "*/backup/schedules")
    assert len(puts) == 1 and puts[0].body["weeklySchedule"] == {**DEFAULTS, "incrementalEvery": 12}
    assert fake.calls("POST", "*/backup/schedules") == []
    assert _schedule(path) == {**DEFAULTS, "incrementalEvery": 12}


@pytest.mark.story("CAP-058", "AC1")
def test_bucket_backup_ac1_set_interactive(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("bucket", "backup", "schedule", "set", "nova-dev-01", "orders", input="monday\n3\n12\n90days\nn\ny\n")
    assert r.exit_code == 0, r.output
    assert fake.calls("POST", "*/backup/schedules")[0].body["weeklySchedule"] == {
        "dayOfWeek": "monday", "startAt": 3, "incrementalEvery": 12, "retentionTime": "90days",
        "costOptimizedRetention": False}


@pytest.mark.story("CAP-058", "AC2")
def test_bucket_backup_ac2_rerun_zero_writes(fake, run, imported):
    assert _set(run, "--day", "friday", "--start-at", "2").exit_code == 0
    fake.reset_calls()
    r = _set(run, "--day", "friday", "--start-at", "2")
    assert r.exit_code == 0 and "already matches" in r.output
    assert "No changes" in run("--auto-approve", "apply").output
    assert fake.writes() == []


@pytest.mark.story("CAP-058", "AC3")
@pytest.mark.parametrize("extra,message", [
    (["--incremental-every", "3"], "backupSchedule.incrementalEvery (line 34)\n    must be one of: 1, 2, 4, 6, 8, 12, 24"),
    (["--retention", "45days"], "backupSchedule.retentionTime (line 35)\n    must be one of: 30days, 60days"),
    (["--day", "someday"], "backupSchedule.dayOfWeek (line 32)\n    must be one of: sunday"),
    (["--start-at", "24"], "backupSchedule.startAt (line 33)\n    must be one of: 0, 1, 2"),
])
def test_bucket_backup_ac3_invalid_values(fake, run, imported, extra, message):
    path, _ = imported
    before = path.read_text(encoding="utf-8")
    r = _set(run, *extra)
    assert r.exit_code == 3 and message in r.output, r.output
    assert fake.calls() == [] and path.read_text(encoding="utf-8") == before  # refused offline


@pytest.mark.story("CAP-058", "AC3")
def test_bucket_backup_ac3_free_tier(fake, run):
    pid = fake.seed_project("nova-dev")
    fid = fake.seed_free_cluster(pid, "try-01")
    fake.seed_bucket(fid, "free-b")
    assert run("import").exit_code == 0
    r = run("--auto-approve", "bucket", "backup", "schedule", "set", "try-01", "free-b")
    assert r.exit_code == 4 and "free-tier clusters have no backups" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-058", "AC4")
def test_bucket_backup_ac4_show(fake, run, imported):
    _, cid = imported
    r = run("bucket", "backup", "schedule", "show", "nova-dev-01", "orders")
    assert r.exit_code == 0 and "has no backup schedule" in r.output
    fake.bucket_backup_schedules[(cid, bucket_id("orders"))] = {"weeklySchedule": {**DEFAULTS, "startAt": 2,
                                                                                    "retentionTime": "1year"}}
    r = run("bucket", "backup", "schedule", "show", "nova-dev-01", "orders")
    assert "weekly full on sunday at 02:00 UTC · incremental every 24 h · kept 1 year" in r.output
    data = json.loads(run("-o", "json", "bucket", "backup", "schedule", "show", "nova-dev-01", "orders").output)
    assert data["type"] == "weekly" and data["weeklySchedule"]["startAt"] == 2


@pytest.mark.story("CAP-058", "AC4")
def test_bucket_backup_ac4_delete_and_missing(fake, run, imported):
    path, cid = imported
    assert _set(run).exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "bucket", "backup", "schedule", "delete", "nova-dev-01", "orders")
    assert r.exit_code == 0, r.output
    assert len(fake.calls("DELETE", "*/backup/schedules")) == 1 and _schedule(path) is None
    fake.reset_calls()
    r = run("--auto-approve", "bucket", "backup", "schedule", "delete", "nova-dev-01", "orders")
    assert r.exit_code == 0 and "has no backup schedule; nothing to do" in r.output and fake.writes() == []


@pytest.mark.story("CAP-058", "AC5")
def test_bucket_backup_ac5_cycles(fake, run, imported):
    _, cid = imported
    fake.seed_bucket_backup(cid, "orders", cycle="cy-1", date="2026-10-18T00:00:00Z")
    fake.seed_bucket_backup(cid, "orders", method="incremental", cycle="cy-1", date="2026-10-19T00:00:00Z")
    fake.seed_bucket_backup(cid, "orders", cycle="cy-2", date="2026-10-25T00:00:00Z")
    fake.seed_bucket_backup(cid, "orders", method="incremental", source="manual", cycle="cy-2",
                            date="2026-10-26T00:00:00Z", status="failed")
    r = run("bucket", "backup", "cycle", "list", "nova-dev-01", "orders")
    lines = r.output.splitlines()
    assert lines[0].split() == ["S.NO", "STARTED", "BACKUPS", "LATEST", "STATUS", "ID"]
    assert lines[1].split() == ["1", "2026-10-25", "00:00", "2", "failed", "cy-2"]
    assert lines[2].split() == ["2", "2026-10-18", "00:00", "2", "ready", "cy-1"]
    r = run("bucket", "backup", "cycle", "get", "nova-dev-01", "orders", "cy-2")
    lines = r.output.splitlines()
    assert lines[0].split() == ["S.NO", "DATE", "METHOD", "SOURCE", "STATUS", "SIZE", "ITEMS", "EXPIRES", "ID"]
    assert lines[1].split()[3:6] == ["incremental", "manual", "failed"]
    assert lines[2].split()[3:6] == ["full", "scheduled", "ready"]
    r = run("bucket", "backup", "cycle", "get", "nova-dev-01", "orders", "nope")
    assert r.exit_code == 1 and "cycle nope of orders not found" in r.output


@pytest.mark.story("CAP-058", "AC6")
def test_bucket_backup_ac6_apply_sync_drift(fake, run, imported):
    path, cid = imported
    key = (cid, bucket_id("orders"))
    fake.bucket_backup_schedules[key] = {"weeklySchedule": {**DEFAULTS, "dayOfWeek": "monday"}}
    r = run("plan")
    assert NO_CHANGES in r.output and "bucket-backup-schedule" not in r.output  # not declared: left alone
    assert "bucket-backup-schedule nova-dev-01/orders  weekly full on monday" in run("drift").output
    assert run("sync").exit_code == 0
    assert _schedule(path) == {**DEFAULTS, "dayOfWeek": "monday"}
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output and fake.writes() == []
    fake.bucket_backup_schedules[key]["weeklySchedule"]["startAt"] = 5  # changed in the Capella UI
    assert "startAt" in run("drift").output
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0 and fake.bucket_backup_schedules[key]["weeklySchedule"]["startAt"] == 0
    del fake.bucket_backup_schedules[key]
    assert run("--auto-approve", "apply").exit_code == 0 and key in fake.bucket_backup_schedules  # recreated


@pytest.mark.story("CAP-058", "AC7")
def test_bucket_backup_ac7_help(run):
    for args in (("schedule", "show"), ("schedule", "set"), ("schedule", "delete"), ("cycle", "list"),
                 ("cycle", "get")):
        r = run("bucket", "backup", *args, "--help")
        assert r.exit_code == 0 and "Examples:" in r.output and "capellactl bucket backup" in r.output, args
    assert "Bucket backup" in run("help", "backup").output
