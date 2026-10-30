"""CAP-061 AC1: every command in docs/backup-restore.md runs, in order, against the fake Capella."""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from tests.fakes.capella import bucket_id

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "backup-restore.md"


def _commands() -> list[str]:
    out = []
    for block in re.findall(r"```bash\n(.*?)```", GUIDE.read_text(encoding="utf-8"), flags=re.S):
        for line in block.replace("\\\n", " ").splitlines():
            line = re.sub(r"\s+#.*$", "", line.strip())
            if line.startswith("capellactl "):
                out.append(line.removeprefix("capellactl "))
    return out


@pytest.mark.story("CAP-061", "AC1")
def test_backup_guide_ac1_steps_run(fake, run):
    pid = fake.seed_project("sandbox")
    cid = fake.seed_cluster(pid, "prod-01")
    copy = fake.seed_cluster(pid, "prod-01-copy")
    fake.seed_bucket(cid, "orders")
    fake.seed_bucket(copy, "orders")
    fake.seed_snapshot(cid, created_at="2026-10-28T02:00:00Z")
    assert run("sync").exit_code == 0
    commands = _commands()
    assert len(commands) >= 15
    for cmd in commands:
        # The reader copies IDs from the lists; the newest of each kind here.
        snapshot = max(fake.snapshots.values(), key=lambda s: s["createdAt"])["id"]
        backup = max(fake.backups.values(), key=lambda b: b["date"])["id"] if fake.backups else "none"
        cmd = cmd.replace("CLUSTER_BACKUP_ID", snapshot).replace("BUCKET_BACKUP_ID", backup)
        r = run("--auto-approve", *shlex.split(cmd))
        assert r.exit_code == 0, f"{cmd}\n{r.output}"
    assert fake.snapshot_schedules[cid]["interval"] == 24
    assert fake.bucket_backup_schedules[(cid, bucket_id("orders"))]["weeklySchedule"]["incrementalEvery"] == 12
    assert any(s["type"] == "onDemand" for s in fake.snapshots.values())
    assert any(b["source"] == "manual" for b in fake.backups.values())
    assert [r["targetClusterID"] for r in fake.bucket_restores] == [cid, copy]
    assert len(fake.snapshot_restores) == 1 and fake.exports
