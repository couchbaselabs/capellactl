# CAP-057 — Cluster backups: list, back up now, keep longer, delete and restore

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E10 Backup & restore | P1 | 5 | CAP-007, CAP-056 | Implemented |

## User story
As an **operator**, I want to list a cluster's backups, take one before a risky change, keep an important one
longer, and restore the cluster from a backup, each with one command, so that I can recover a cluster without the
Capella UI.

## Context & discovery
- Second half of the customer request in CAP-056: the cloud snapshot backups themselves. Bucket backups are
  CAP-059.

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| List | `GET …/clusters/{clusterId}/cloudsnapshotbackups` | 200 | `id`, `createdAt`, `expiration`, `progress.status`, `type`, `databaseSize`, `crossRegionCopies[]`, `retention` |
| List (project) | `GET …/projects/{projectId}/cloudsnapshotbackups` | 200 | Every cluster of the project |
| Create | `POST …/clusters/{clusterId}/cloudsnapshotbackups` | 202 | Optional `retention` (hours), `regionsToCopy` (at most two) |
| Edit retention | `PUT …/cloudsnapshotbackups/{backupId}` | 204 | `retention` (hours) |
| Delete | `DELETE …/cloudsnapshotbackups/{backupId}` | 204 | |
| Restore | `POST …/cloudsnapshotbackups/{backupId}/restore` | 202 | Optional `crossRegionRestorePreference` |
| List restores | `GET …/cloudsnapshotbackups/restores` | 200 | `status`, `createdAt`, `restoreEnd`, `snapshot` |
| Copy regions | `GET …/cloudsnapshotbackups/regions` | 200 | Shared with CAP-056 |

A restore replaces the cluster's data with the snapshot, so it is guarded like `cluster delete`.

## Design

### Commands
```
capellactl cluster backup list     [NAME] [--all]
capellactl cluster backup create   NAME [--retain DURATION] [--copy-to REGION …]
capellactl cluster backup retain   NAME BACKUP_ID --retain DURATION
capellactl cluster backup delete   NAME BACKUP_ID
capellactl cluster backup restore  NAME BACKUP_ID [--from-region REGION …]
capellactl cluster backup restores NAME
capellactl cluster backup regions  NAME
```
Shared flags: `--project`, global `--auto-approve`, `--no-wait`, `--timeout`, `-o json`.

Examples:
```
capellactl cluster backup list nova-prod-01
capellactl cluster backup create nova-prod-01
capellactl cluster backup retain nova-prod-01 3f1c… --retain 90d
capellactl cluster backup restore nova-prod-01 3f1c…
```

- **list** uses the list layout of every list (S.NO first, ID last):
  `S.NO  CREATED  TYPE  STATUS  SIZE  EXPIRES  COPIES  ID`, newest first. Without `NAME` (or with `--all`) it uses
  the project-level endpoint and adds a `CLUSTER` column after S.NO.
- **create** waits until the backup's `progress.status` is complete (CAP-007 waiter) unless `--no-wait`, then prints
  its ID. It is an action, like `cluster power`: each run takes a new backup and nothing is written to capella.yaml.
- **retain** changes how long one backup is kept.
- **delete** asks for the backup's creation time to be typed (or `--auto-approve`).
- **restore** prints what will be replaced (`all data of nova-prod-01 is replaced with the backup of
  2026-10-28 02:00 UTC`), asks for the cluster name to be typed (or `--auto-approve`), sends the restore and waits
  until the restore's status is complete and the cluster is `healthy`.
- **restores** lists past restores in the same layout: `S.NO  STARTED  FINISHED  SNAPSHOT  STATUS  ID`.

### Where the code goes
- `cli/cluster_backup.py` (from CAP-056): the verbs above.
- `api/endpoints.py`, fake Capella, refreshed responses file.

## Acceptance criteria & tests

### AC1 — List
**Given** a cluster with three backups, **then** `cluster backup list NAME` prints three rows, newest first, with
S.NO first and ID last; `-o json` returns Capella's items. **Given** no `NAME`, **then** the project-level endpoint
is used and the `CLUSTER` column is shown. **Given** no backups, `no backups`, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac1_list` | `tests/scenario/test_cluster_backup.py` | Text, JSON, empty |
| `test_cluster_backup_ac1_list_project` | same | |

### AC2 — Back up now
**Given** `cluster backup create nova-dev-01 --retain 7d`, **then** one `POST` with `retention: 168` is sent, the
tool waits until the backup is complete and prints its ID; with `--no-wait` it returns after the `202`. More than two
`--copy-to` regions, or a region not offered, exits 3 with zero writes. A free-tier cluster exits 4.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac2_create_waits` | `tests/scenario/test_cluster_backup.py` | |
| `test_cluster_backup_ac2_create_refused` | same | Parametrised |

### AC3 — Keep a backup longer
**Given** `retain … --retain 90d`, **then** one `PUT` with `retention: 2160`. **Given** the backup already has that
retention, **then** `no changes`, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac3_retain` | `tests/scenario/test_cluster_backup.py` | |
| `test_cluster_backup_ac3_retain_rerun_noop` | same | |

### AC4 — Delete
**Given** a backup, **then** `delete` asks for the typed confirmation and sends one `DELETE`. **Given** an unknown
ID, **then** `backup … not found`, exit 0 with `--auto-approve` and zero writes, so scripts can re-run.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac4_delete` | `tests/scenario/test_cluster_backup.py` | |
| `test_cluster_backup_ac4_delete_missing_noop` | same | |

### AC5 — Restore
**Given** `restore nova-dev-01 ID`, **then** the plan says all data is replaced, a wrong typed name sends nothing
(exit 5 as for `cluster delete`), the right one sends one `POST …/restore`, and the tool waits until the restore is
complete and the cluster is healthy. **Given** a cluster that is `turnedOff`, **then** exit 4 `turned off; power it
on before restoring` with zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac5_restore_confirm` | `tests/scenario/test_cluster_backup.py` | |
| `test_cluster_backup_ac5_restore_waits` | same | |
| `test_cluster_backup_ac5_restore_turned_off` | same | |

### AC6 — Restores and regions
**Given** past restores, **then** `restores` lists them in the list layout; `regions` lists the copy regions.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac6_restores_and_regions` | `tests/scenario/test_cluster_backup.py` | |

### AC7 — Discoverable
**Given** `cluster backup --help`, **then** every verb has an example, and `docs/runbook.md` has "Take a cluster
backup before a change" and "Restore a cluster from a backup".

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac7_help` | `tests/scenario/test_cluster_backup.py` | |

## Out of scope
- **Clone a backup into a new cluster** (`POST …/projects/{p}/cloudsnapshotbackups/{backupId}/clone`): creates a
  cluster outside capella.yaml, so it needs the CAP-038 record-then-apply design. Proposed as `cluster backup clone`
  for 1.1.

## Open questions
- What are `progress.status` and the restore `status` values? The spec gives them as free strings; the fake and the
  waiter use the values seen in the sandbox, recorded in the responses file.

## Implementation notes (as built)
- `capellactl/cli/cluster_backup.py`: `list`, `create`, `retain`, `delete`, `restore`, `restores`, `regions`.
- **`list` without NAME** uses the project-level endpoint, which returns one summary per cluster (its newest and
  oldest backup), not every backup. The table is `S.NO CLUSTER REGION NEWEST OLDEST CLUSTER ID`; there is no
  `--all` flag (`--project` chooses the project).
- **Confirmations**: `delete` asks for the cluster name (like every typed confirmation), not the backup's creation
  time. A wrong name prints `Cancelled; nothing was …` and exits 0, as `cluster delete` does (the story's "exit 5"
  was wrong: 5 is the timeout code).
- `create` and `restore` wait with the new `wait_for_status` (engine/waiter.py, the cluster waiter's poll intervals):
  `create` until the backup's `progress.status` is done; `restore` until the restore is done and then until the
  cluster is healthy. `--no-wait` returns after the 202.
- The spec gives `progress.status` and the restore `status` as free text; capellactl treats `complete`, `completed`,
  `succeeded`, `success`, `done` and `ready` as done and `failed`, `error`, `cancelled` and `expired` as failed
  (`cli/backup_common.py`). **Still open:** confirm the values on the sandbox's first run (CAP-032).
- Cloning a backup into a new cluster stays out of scope (`cluster backup clone`, proposed for 1.1).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_cluster_backup_ac1_list`, `test_cluster_backup_ac1_list_project` (tests/scenario/test_cluster_backup.py) |
| AC2 | `test_cluster_backup_ac2_create_waits`, `test_cluster_backup_ac2_create_refused` |
| AC3 | `test_cluster_backup_ac3_retain`, `test_cluster_backup_ac3_retain_rerun_noop` |
| AC4 | `test_cluster_backup_ac4_delete`, `test_cluster_backup_ac4_delete_missing_noop` |
| AC5 | `test_cluster_backup_ac5_restore_confirm`, `test_cluster_backup_ac5_restore_waits`, `test_cluster_backup_ac5_restore_turned_off` |
| AC6 | `test_cluster_backup_ac6_restores_and_regions` |
| AC7 | `test_cluster_backup_ac7_help` |
