"""CAP-061 AC3–AC5: the backup and disk-type guides are live, easy to find and work in PowerShell."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.unit.docs.test_windows_docs import _bash_only, _shell_lines

ROOT = Path(__file__).resolve().parents[3]
BACKUP = (ROOT / "docs" / "backup-restore.md").read_text(encoding="utf-8")
CUSTOM = (ROOT / "docs" / "custom-clusters.md").read_text(encoding="utf-8")
DOCS = [*sorted((ROOT / "docs").glob("*.md")), ROOT / "README.md", *sorted((ROOT / "capellactl" / "help").glob("*.md"))]


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start:nxt if nxt > 0 else None]


@pytest.mark.story("CAP-061", "AC3")
def test_backup_guide_ac3_no_planned_notes():
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        assert not re.search(r"(?i)planned for (release )?1\.0\.0|disk type \(planned\)|CAP-061\)? turns them",
                             text), doc.name
    disk = _section(CUSTOM, "## 4. Choose each group's disk")
    for text in (BACKUP, disk):
        blocks = re.findall(r"```(\w*)\n(.*?)```", text, flags=re.S)
        commands = [lang for lang, body in blocks if body.lstrip().startswith("capellactl ")]
        assert commands and set(commands) == {"bash"}, "every command block is ```bash (checked by CI)"


@pytest.mark.story("CAP-061", "AC4")
def test_backup_guide_ac4_linked():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    assert "[Backup and restore](docs/backup-restore.md)" in readme
    assert "[Backup and restore](backup-restore.md)" in _section(guide, "### Manage a provisioned cluster")
    assert "custom-clusters.md#4-choose-each-groups-disk" in guide
    assert "docs/backup-restore.md" in (ROOT / "capellactl" / "help" / "backup.md").read_text(encoding="utf-8")
    assert "capellactl cluster disk-types" in (ROOT / "capellactl" / "help" / "scaling.md").read_text(encoding="utf-8")
    for heading in ("## Change a disk type", "## Set a cluster backup schedule", "## Set a bucket backup schedule",
                    "## Take a cluster backup before a change", "## Restore a cluster from a backup",
                    "## Restore a bucket from a backup", "## Download a bucket backup", "## Backups"):
        assert heading in runbook, heading
    assert "[backup-restore.md](backup-restore.md)" in runbook


@pytest.mark.story("CAP-061", "AC5")
def test_backup_guide_ac5_powershell_scan_covers_it():
    lines = _shell_lines()
    ours = [line for line in lines if "backup schedule set prod-01" in line or "disk-types --provider aws" in line]
    assert ours, "the CAP-055 PowerShell scan reads backup-restore.md and custom-clusters.md"
    assert not [line for line in ours if _bash_only(line.split(" #")[0])]
