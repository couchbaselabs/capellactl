"""CAP-057: cluster backups (cloud snapshots): list, back up now, keep longer, delete and restore."""
from __future__ import annotations

import json

import pytest

from capellactl.cli import console
from tests.conftest import seed_healthy


@pytest.fixture
def imported(fake, run, tmp_path):
    pid, cid = seed_healthy(fake)
    assert run("import").exit_code == 0
    fake.reset_calls()
    return cid


@pytest.fixture
def three(fake, imported):
    ids = [fake.seed_snapshot(imported, created_at=f"2026-10-2{d}T02:00:00Z") for d in (6, 8, 7)]
    return imported, ids


@pytest.mark.story("CAP-057", "AC1")
def test_cluster_backup_ac1_list(fake, run, three):
    cid, ids = three
    r = run("cluster", "backup", "list", "nova-dev-01")
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0].split() == ["S.NO", "CREATED", "TYPE", "STATUS", "SIZE", "EXPIRES", "COPIES", "ID"]
    assert [line.split()[-1] for line in lines[1:]] == [ids[1], ids[2], ids[0]]  # newest first, ID last
    assert lines[1].split()[:3] == ["1", "2026-10-28", "02:00"] and "42 GB" in lines[1]
    data = json.loads(run("-o", "json", "cluster", "backup", "list", "nova-dev-01").output)
    assert {s["id"] for s in data} == set(ids)
    for i in ids:
        del fake.snapshots[i]
    assert "no backups" in run("cluster", "backup", "list", "nova-dev-01").output
    assert fake.writes() == []


@pytest.mark.story("CAP-057", "AC1")
def test_cluster_backup_ac1_list_project(fake, run, three):
    r = run("cluster", "backup", "list")
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0].split() == ["S.NO", "CLUSTER", "REGION", "NEWEST", "OLDEST", "CLUSTER", "ID"]
    assert lines[1].split()[:6] == ["1", "nova-dev-01", "us-east-1", "2026-10-28", "02:00", "2026-10-26"]
    assert fake.calls("GET", "*/projects/*/cloudsnapshotbackups")


@pytest.mark.story("CAP-057", "AC2")
def test_cluster_backup_ac2_create_waits(fake, run, imported):
    r = run("--auto-approve", "cluster", "backup", "create", "nova-dev-01", "--retain", "7d", "--copy-to", "us-west-2")
    assert r.exit_code == 0, r.output
    posts = fake.calls("POST", "*/cloudsnapshotbackups")
    assert len(posts) == 1 and posts[0].body == {"retention": 168, "regionsToCopy": ["us-west-2"]}
    backup_id = next(iter(fake.snapshots))
    assert "backup of nova-dev-01: pending" in r.output and f"backup {backup_id} of nova-dev-01 is complete" in r.output
    r = run("--auto-approve", "--no-wait", "cluster", "backup", "create", "nova-dev-01")
    assert r.exit_code == 0 and "started (--no-wait)" in r.output and "complete" not in r.output


@pytest.mark.story("CAP-057", "AC2")
@pytest.mark.parametrize("extra,message", [
    (["--copy-to", "us-east-2", "--copy-to", "us-west-2", "--copy-to", "eu-west-1"], "at most two regions"),
    (["--copy-to", "mars-1"], "copies cannot go to mars-1"),
    (["--retain", "soon"], "--retain takes hours or days"),
])
def test_cluster_backup_ac2_create_refused(fake, run, imported, extra, message):
    r = run("--auto-approve", "cluster", "backup", "create", "nova-dev-01", *extra)
    assert r.exit_code == 3 and message in r.output, r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-057", "AC3")
def test_cluster_backup_ac3_retain(fake, run, three):
    cid, ids = three
    r = run("--auto-approve", "cluster", "backup", "retain", "nova-dev-01", ids[0], "--retain", "90d")
    assert r.exit_code == 0, r.output
    puts = fake.calls("PUT", "*/cloudsnapshotbackups/*")
    assert len(puts) == 1 and puts[0].body == {"retention": 2160}
    assert "is now kept 90 days (was 30 days)" in r.output
    r = run("cluster", "backup", "retain", "nova-dev-01", "nope", "--retain", "90d")
    assert r.exit_code == 1 and "backup nope of nova-dev-01 not found" in r.output


@pytest.mark.story("CAP-057", "AC3")
def test_cluster_backup_ac3_retain_rerun_noop(fake, run, three):
    _, ids = three
    assert run("cluster", "backup", "retain", "nova-dev-01", ids[0], "--retain", "90d").exit_code == 0
    fake.reset_calls()
    r = run("cluster", "backup", "retain", "nova-dev-01", ids[0], "--retain", "2160h")
    assert r.exit_code == 0 and "No changes" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-057", "AC4")
def test_cluster_backup_ac4_delete(fake, run, three, monkeypatch):
    _, ids = three
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "backup", "delete", "nova-dev-01", ids[0], input="nova\n")
    assert r.exit_code == 0 and "Cancelled; nothing was deleted." in r.output
    assert fake.writes() == []
    r = run("cluster", "backup", "delete", "nova-dev-01", ids[0], input="nova-dev-01\n")
    assert r.exit_code == 0, r.output
    assert len(fake.calls("DELETE", "*/cloudsnapshotbackups/*")) == 1 and ids[0] not in fake.snapshots


@pytest.mark.story("CAP-057", "AC4")
def test_cluster_backup_ac4_delete_missing_noop(fake, run, three):
    r = run("--auto-approve", "cluster", "backup", "delete", "nova-dev-01", "nope")
    assert r.exit_code == 0 and "not found, nothing to do" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-057", "AC5")
def test_cluster_backup_ac5_restore_confirm(fake, run, three, monkeypatch):
    _, ids = three
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "backup", "restore", "nova-dev-01", ids[1], input="other\n")
    assert r.exit_code == 0, r.output
    assert "all data is replaced with the backup of 2026-10-28 02:00 UTC" in r.output
    assert "Cancelled; nothing was restored." in r.output and fake.writes() == []
    monkeypatch.setattr(console, "is_interactive", lambda: False)
    r = run("cluster", "backup", "restore", "nova-dev-01", ids[1])
    assert r.exit_code != 0 and fake.writes() == []  # no terminal and no --auto-approve: refused


@pytest.mark.story("CAP-057", "AC5")
def test_cluster_backup_ac5_restore_waits(fake, run, three):
    cid, ids = three
    r = run("--auto-approve", "cluster", "backup", "restore", "nova-dev-01", ids[1], "--from-region", "us-west-2")
    assert r.exit_code == 0, r.output
    posts = fake.calls("POST", "*/cloudsnapshotbackups/*/restore")
    assert len(posts) == 1 and posts[0].body == {"crossRegionRestorePreference": ["us-west-2"]}
    assert "restore of nova-dev-01: complete" in r.output and "cluster nova-dev-01: healthy" in r.output
    assert "restored cluster nova-dev-01 from the backup of 2026-10-28 02:00 UTC" in r.output


@pytest.mark.story("CAP-057", "AC5")
def test_cluster_backup_ac5_restore_turned_off(fake, run, three):
    cid, ids = three
    fake.set_transition(cid, ["turnedOff"])
    r = run("--auto-approve", "cluster", "backup", "restore", "nova-dev-01", ids[1])
    assert r.exit_code == 4 and "turned off; power it on before restoring" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-057", "AC6")
def test_cluster_backup_ac6_restores_and_regions(fake, run, three):
    _, ids = three
    assert "no restores" in run("cluster", "backup", "restores", "nova-dev-01").output
    assert run("--auto-approve", "cluster", "backup", "restore", "nova-dev-01", ids[0]).exit_code == 0
    r = run("cluster", "backup", "restores", "nova-dev-01")
    lines = r.output.splitlines()
    assert lines[0].split() == ["S.NO", "STARTED", "FINISHED", "SNAPSHOT", "STATUS", "ID"]
    assert "complete" in lines[1] and "2026-10-26 02:00" in lines[1]
    r = run("cluster", "backup", "regions", "nova-dev-01")
    assert r.output.splitlines()[0].split() == ["S.NO", "REGION"] and "us-west-2" in r.output


@pytest.mark.story("CAP-057", "AC7")
def test_cluster_backup_ac7_help(run):
    r = run("cluster", "backup", "--help")
    assert r.exit_code == 0
    for verb in ("list", "create", "retain", "delete", "restore", "restores", "regions", "schedule"):
        assert verb in r.output, verb
        h = run("cluster", "backup", verb, "--help")
        assert h.exit_code == 0 and "Examples:" in h.output, verb
