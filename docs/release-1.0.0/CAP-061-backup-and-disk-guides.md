# CAP-061 — Guides: backup and restore, and choosing a disk type, as steps CI runs

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E10 Backup & restore | P1 | 3 | CAP-056, CAP-057, CAP-058, CAP-059, CAP-060 | Implemented |

## User story
As a **customer operator**, I want one guide that walks me through backup and restore, and a section of the custom
cluster guide on disk types, with commands I can copy and the output I should see, so that I can try the new
features without reading the stories or the API reference.

## Context & discovery
- Requested 2026-10-29 together with CAP-056–CAP-060: "update the commands for user to try by adding into the
  appropriate guide book".
- Where the commands go, and why:
  - **Backup and restore → a new guide, `docs/backup-restore.md`.** It spans cluster and bucket commands, schedules,
    restores and capella.yaml, which is too much for a section of `getting-started.md` (already long, and run end to
    end by CAP-033 AC5). It follows the shape of `docs/custom-clusters.md`: concepts in one table, numbered steps,
    output, troubleshooting. The README Documentation table links it; `getting-started.md` points to it from
    "Manage a provisioned cluster".
  - **Disk types → `docs/custom-clusters.md` §10.** That guide already covers choosing node sizes per service group;
    the disk is chosen in the same place (`--group … :DISK`, `cluster group add`, the interactive picker).
  - **Day-2 tasks → `docs/runbook.md`**, as each backup story's AC7 says (set a schedule, back up before a change,
    restore a cluster, restore a bucket, download a backup, change a disk type).
- The guide text was written with the stories (2026-10-29) and is in the repository already, marked *planned*, with
  commands in ```` ```text ```` blocks. Only ```` ```bash ```` blocks are run or parsed by CI
  (`tests/unit/docs/test_doc_commands.py`, `tests/scenario/test_custom_clusters_guide.py`), so the planned commands
  do not break CI before they exist. This story makes them real.

## Design
- When CAP-056–CAP-060 are Implemented: change the guides' ```` ```text ```` command blocks to ```` ```bash ```` (output
  blocks stay plain), remove the *planned* notes in `docs/backup-restore.md`, `docs/custom-clusters.md` §10 and the
  README row, and correct example output to what the commands print.
- `tests/scenario/test_backup_restore_guide.py` (new) runs every command of `docs/backup-restore.md`, in order,
  against the fake Capella, like `test_custom_clusters_guide.py`; `test_custom_clusters_guide.py` gains the §10
  commands and asserts the disks the fake received.
- `help backup` (CAP-056) and `help scaling` (CAP-060) end with a pointer to the guide.

## Acceptance criteria & tests

### AC1 — The backup guide runs
**Given** the fake Capella with project `sandbox`, cluster `prod-01` and bucket `orders`, **then** every
`capellactl` line in `docs/backup-restore.md` runs in order with `--auto-approve` and exits 0 (or the exit code the
guide shows on purpose), and the fake holds the cluster schedule, the bucket schedule, one on-demand backup of each
kind and one restore of each kind.

| Test | Location | Verifies |
|---|---|---|
| `test_backup_guide_ac1_steps_run` | `tests/scenario/test_backup_restore_guide.py` | |

### AC2 — The disk section runs
**Given** `docs/custom-clusters.md` §10, **then** its commands run in `test_custom_clusters_guide.py` and the fake's
`prod-05` has `gp3 200 GB 5740 IOPS` on data, `io2` on search, and `io2 20000 IOPS` on data after the update.

| Test | Location | Verifies |
|---|---|---|
| `test_disk_guide_ac2_steps_run` | `tests/scenario/test_custom_clusters_guide.py` | |

### AC3 — No planned leftovers
**Given** the docs, **then** no guide, README row or help page says *planned* or *not available yet* for a command that
exists, and every command block of the two guides is ```` ```bash ````, so `test_docs_ac2_commands_parse` checks them.

| Test | Location | Verifies |
|---|---|---|
| `test_backup_guide_ac3_no_planned_notes` | `tests/unit/docs/test_backup_guide.py` | |

### AC4 — Easy to find
**Given** the README Documentation table, `getting-started.md` "Manage a provisioned cluster", `help backup` and
`help scaling`, **then** each links to the guide or section; `docs/runbook.md` has the six day-2 tasks above and its
commands are parsed in CI.

| Test | Location | Verifies |
|---|---|---|
| `test_backup_guide_ac4_linked` | `tests/unit/docs/test_backup_guide.py` | |

### AC5 — Works in Windows PowerShell
**Given** the new command lines, **then** none uses a bash-only construct without a row in the getting-started
PowerShell translation table (CAP-055 AC5 scan extended to `backup-restore.md`).

| Test | Location | Verifies |
|---|---|---|
| `test_windows_docs_ac5_translation_table_complete` | `tests/unit/docs/test_windows_docs.py` | Extended file list |

## Out of scope
- A video or slide walkthrough.

## Implementation notes (as built)
- `docs/backup-restore.md`: nine steps, from the options to a download, with `bash` command blocks. IDs the reader
  copies from a list are written `CLUSTER_BACKUP_ID` and `BUCKET_BACKUP_ID`; the test puts in the fake's newest.
- `docs/custom-clusters.md` §10 "Choose the disk type" is live; its commands create `prod-05` with gp3, add an io2
  search group and change the data group to io2.
- `docs/runbook.md`: Part 1 has "Change a disk type", "Set a cluster backup schedule", "Set a bucket backup
  schedule", "Take a cluster backup before a change", "Restore a cluster from a backup", "Restore a bucket from a
  backup" and "Download a bucket backup"; Part 2 has a "Backups" section, `cluster disk-types` and
  `cluster update --disk-type`, and a corrected Azure disk note.
- README Documentation table, `getting-started.md` (step 11), `help backup` and `help scaling` link the guides.
- The CAP-055 PowerShell scan reads `backup-restore.md` too.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_backup_guide_ac1_steps_run` (tests/scenario/test_backup_restore_guide.py) |
| AC2 | `test_disk_guide_ac2_steps_run` (tests/scenario/test_custom_clusters_guide.py) |
| AC3 | `test_backup_guide_ac3_no_planned_notes` (tests/unit/docs/test_backup_guide.py) |
| AC4 | `test_backup_guide_ac4_linked` |
| AC5 | `test_backup_guide_ac5_powershell_scan_covers_it` |

- Guide revision (2026-10-30, customer report): every step of `docs/backup-restore.md` now has a table of its
  command's options (default and meaning) before the command; the options all commands share (`--project`,
  `--no-apply`, `--no-wait`, `--auto-approve`, `--timeout`) are explained once, in "Options every backup command
  takes".
