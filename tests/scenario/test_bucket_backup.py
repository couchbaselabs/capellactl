"""CAP-059: bucket backups: list, back up now, delete, restore and export."""
from __future__ import annotations

import json

import pytest

from capellactl.cli import console
from tests.conftest import seed_healthy
from tests.fakes.capella import bucket_id


@pytest.fixture
def world(fake, run):
    pid, cid = seed_healthy(fake)
    dr = fake.seed_cluster(pid, "nova-dr-01")
    fake.seed_bucket(cid, "orders")
    fake.seed_bucket(cid, "users")
    full = fake.seed_bucket_backup(cid, "orders", cycle="cy-1", date="2026-10-25T02:00:00Z")
    inc = fake.seed_bucket_backup(cid, "orders", method="incremental", cycle="cy-1", date="2026-10-26T02:00:00Z")
    users = fake.seed_bucket_backup(cid, "users", source="manual", cycle="cy-u", date="2026-10-24T02:00:00Z")
    assert run("import").exit_code == 0
    fake.reset_calls()
    return {"cid": cid, "dr": dr, "full": full, "inc": inc, "users": users}


@pytest.mark.story("CAP-059", "AC1")
def test_bucket_backup_ac1_list(fake, run, world):
    r = run("bucket", "backup", "list", "nova-dev-01")
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0].split() == ["S.NO", "BUCKET", "DATE", "METHOD", "SOURCE", "STATUS", "SIZE", "ITEMS", "EXPIRES", "ID"]
    assert [line.split()[1] for line in lines[1:]] == ["orders", "users"]  # the latest of each bucket, newest first
    assert lines[1].split()[-1] == world["inc"]
    r = run("bucket", "backup", "list", "nova-dev-01", "orders")
    assert [line.split()[-1] for line in r.output.splitlines()[1:]] == [world["inc"], world["full"]]
    data = json.loads(run("-o", "json", "bucket", "backup", "list", "nova-dev-01").output)
    assert {b["bucketName"] for b in data} == {"orders", "users"}
    fake.backups.clear()
    assert "no backups" in run("bucket", "backup", "list", "nova-dev-01").output
    assert fake.writes() == []


@pytest.mark.story("CAP-059", "AC1")
def test_bucket_backup_ac1_get(fake, run, world):
    r = run("bucket", "backup", "get", "nova-dev-01", world["full"])
    assert r.exit_code == 0, r.output
    assert "orders" in r.output and "full" in r.output and "cycle cy-1" in r.output and "indexes 2" in r.output
    assert json.loads(run("-o", "json", "bucket", "backup", "get", "nova-dev-01", world["full"]).output)["id"] == \
        world["full"]
    r = run("bucket", "backup", "get", "nova-dev-01", "nope")
    assert r.exit_code == 1 and "backup nope not found" in r.output


@pytest.mark.story("CAP-059", "AC2")
def test_bucket_backup_ac2_create(fake, run, world):
    r = run("--auto-approve", "bucket", "backup", "create", "nova-dev-01", "orders")
    assert r.exit_code == 0, r.output
    posts = fake.calls("POST", "*/buckets/*/backups")
    assert len(posts) == 1 and posts[0].path.endswith(f"/buckets/{bucket_id('orders')}/backups")
    new = next(i for i, b in fake.backups.items() if b["source"] == "manual" and b["bucketName"] == "orders")
    assert "backup of orders: ready" in r.output and f"backup {new} of orders is ready" in r.output
    r = run("--auto-approve", "--no-wait", "bucket", "backup", "create", "nova-dev-01", "users")
    assert r.exit_code == 0 and "started (--no-wait)" in r.output


@pytest.mark.story("CAP-059", "AC2")
def test_bucket_backup_ac2_create_failed_and_refused(fake, run, world):
    fake.backup_fails_next = True
    r = run("--auto-approve", "bucket", "backup", "create", "nova-dev-01", "orders")
    assert r.exit_code == 1 and "backup of orders ended failed" in r.output
    fake.reset_calls()
    r = run("--auto-approve", "bucket", "backup", "create", "nova-dev-01", "nope")
    assert r.exit_code == 1 and "bucket nope not found in cluster nova-dev-01" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-059", "AC3")
def test_bucket_backup_ac3_delete_cycle(fake, run, world, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("bucket", "backup", "delete", "nova-dev-01", world["inc"], input="users\n")
    assert "deletes cycle 2026-10-25 02:00 with 2 backups of orders" in r.output
    assert "Cancelled" in r.output and fake.writes() == []
    r = run("bucket", "backup", "delete", "nova-dev-01", world["inc"], input="orders\n")
    assert r.exit_code == 0, r.output
    assert len(fake.calls("DELETE", "*/backups/*")) == 1
    assert world["full"] not in fake.backups and world["inc"] not in fake.backups and world["users"] in fake.backups


@pytest.mark.story("CAP-059", "AC3")
def test_bucket_backup_ac3_delete_missing_noop(fake, run, world):
    r = run("--auto-approve", "bucket", "backup", "delete", "nova-dev-01", "nope")
    assert r.exit_code == 0 and "not found in cluster nova-dev-01, nothing to do" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-059", "AC4")
def test_bucket_backup_ac4_restore_same_cluster(fake, run, world):
    r = run("--auto-approve", "bucket", "backup", "restore", "nova-dev-01", world["full"])
    assert r.exit_code == 0, r.output
    assert "restore orders from the backup of 2026-10-25 02:00 UTC into nova-dev-01" in r.output
    assert "newer documents in nova-dev-01 are kept" in r.output
    posts = fake.calls("POST", "*/backups/*/restore")
    assert len(posts) == 1 and posts[0].body == {"targetClusterID": world["cid"], "sourceClusterID": world["cid"],
                                                 "backupID": world["full"], "services": ["data"]}
    assert "restore of orders into nova-dev-01 started" in r.output


@pytest.mark.story("CAP-059", "AC4")
def test_bucket_backup_ac4_restore_confirm(fake, run, world, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("bucket", "backup", "restore", "nova-dev-01", world["full"], input="orders\n")
    assert r.exit_code == 0 and "Cancelled; nothing was restored." in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-059", "AC5")
def test_bucket_backup_ac5_restore_options_body(fake, run, world):
    r = run("--auto-approve", "bucket", "backup", "restore", "nova-dev-01", world["full"], "--to-cluster", "nova-dr-01",
            "--include-data", "orders.sales", "--map-data", "orders=orders_copy", "--replace-ttl", "all",
            "--replace-ttl-with", "2027-01-01T00:00:00Z", "--services", "query,data", "--force-updates",
            "--auto-remove-collections", "--filter-keys", "^order::")
    assert r.exit_code == 0, r.output
    assert "into nova-dr-01" in r.output and "overwrites newer documents (--force-updates)" in r.output
    assert fake.calls("POST", "*/backups/*/restore")[0].body == {
        "targetClusterID": world["dr"], "sourceClusterID": world["cid"], "backupID": world["full"],
        "services": ["data", "query"], "includeData": "orders.sales", "mapData": "orders=orders_copy",
        "filterKeys": "^order::", "replaceTTL": "all", "replaceTTLWith": "2027-01-01T00:00:00Z", "forceUpdates": True,
        "autoRemoveCollections": True}


@pytest.mark.story("CAP-059", "AC5")
@pytest.mark.parametrize("extra,code,message", [
    (["--replace-ttl-with", "2027-01-01T00:00:00Z"], 3, "--replace-ttl-with needs --replace-ttl all"),
    (["--replace-ttl", "none", "--replace-ttl-with", "2027-01-01T00:00:00Z"], 3, "--replace-ttl-with needs"),
    (["--services", "data,index"], 3, "--services takes data, query or data,query"),
    (["--to-cluster", "nope-01"], 1, "cluster nope-01 not found"),
])
def test_bucket_backup_ac5_restore_refused(fake, run, world, extra, code, message):
    r = run("--auto-approve", "bucket", "backup", "restore", "nova-dev-01", world["full"], *extra)
    assert r.exit_code == code and message in r.output, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-059", "AC5")
def test_bucket_backup_ac5_restore_target_turned_off(fake, run, world):
    fake.set_transition(world["dr"], ["turnedOff"])
    r = run("--auto-approve", "bucket", "backup", "restore", "nova-dev-01", world["full"], "--to-cluster", "nova-dr-01")
    assert r.exit_code == 4 and "nova-dr-01 is turned off" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-059", "AC6")
def test_bucket_backup_ac6_export(fake, run, world):
    r = run("--auto-approve", "bucket", "backup", "export", "nova-dev-01", world["full"])
    assert r.exit_code == 0, r.output
    assert len(fake.calls("POST", "*/backups/*/export")) == 1
    export_id = next(iter(fake.exports))
    assert f"export {export_id} of orders started" in r.output and "export of orders: complete" in r.output
    assert "treat it like a password" in r.output and "X-Amz-Signature=s3cr3t" in r.output
    fake.reset_calls()
    r = run("bucket", "backup", "export", "nova-dev-01", world["full"], "--export-id", export_id)
    assert r.exit_code == 0 and f"export {export_id} is complete" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-059", "AC6")
def test_bucket_backup_ac6_export_existing_and_refused(fake, run, world):
    r = run("--log-level", "debug", "bucket", "backup", "export", "nova-dev-01", world["full"])
    assert r.exit_code == 0 and "/exports/" in r.output  # the debug request lines are there …
    assert r.output.count("X-Amz-Signature=s3cr3t") == 1  # … and the link only once: printed, never logged
    fake.reset_calls()
    r = run("bucket", "backup", "export", "nova-dev-01", world["inc"])  # same cycle
    assert r.exit_code == 0 and "already has an export (Capella allows one per cycle)" in r.output
    assert len(fake.writes()) == 1  # the refused POST only
    fake.backups[world["users"]]["status"] = "pending"
    r = run("bucket", "backup", "export", "nova-dev-01", world["users"])
    assert r.exit_code == 4 and "Capella cannot export this backup" in r.output and "ready state" in r.output


@pytest.mark.story("CAP-059", "AC7")
def test_bucket_backup_ac7_help(run):
    r = run("bucket", "backup", "--help")
    assert r.exit_code == 0
    for verb in ("list", "get", "create", "delete", "restore", "export", "schedule", "cycle"):
        assert verb in r.output, verb
        h = run("bucket", "backup", verb, "--help")
        assert h.exit_code == 0 and "Examples:" in h.output, verb
