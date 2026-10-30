# CAP-059 — Bucket backups: list, back up now, delete, restore and export

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E10 Backup & restore | P1 | 8 | CAP-007, CAP-058 | Implemented |

## User story
As an **operator**, I want to list a bucket's backups, back a bucket up now, restore it (to the same or another
cluster, all or part of the data) and download a backup, each with one command, so that I can recover or move one
bucket's data without the Capella UI.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Create | `POST …/buckets/{bucketId}/backups` | 202 | On-demand backup |
| List | `GET …/clusters/{clusterId}/backups` | 200 | Latest backup of each bucket's cycles in the cluster: `status` (`pending`, `ready`, `failed`), `method` (`full`, `incremental`), `source` (`manual`, `scheduled`), `stats.sizeInMb`, `stats.items`, `restoreBefore` |
| Get | `GET …/clusters/{clusterId}/backups/{backupId}` | 200 | |
| Delete | `DELETE …/clusters/{clusterId}/backups/{backupId}` | 202 | **Deletes the whole cycle** the backup belongs to |
| Restore | `POST …/clusters/{clusterId}/backups/{backupId}/restore` | 202 | `targetClusterID`, `sourceClusterID`, `backupID`, `services` (`data`, `query`) required; optional `forceUpdates`, `autoRemoveCollections`, `filterKeys`, `filterValues`, `includeData`, `excludeData`, `mapData`, `replaceTTL` (`none`, `all`, `expired`), `replaceTTLWith` |
| Export | `POST …/buckets/{bucketId}/backups/{backupId}/export` | 202 | Packages a backup cycle as a zip. **New in the spec after the 2026-10-06 snapshot.** 422 unless the backup is `ready`, at most 5 TB and its cycle complete; 409 when the cycle already has an export |
| Get export | `GET …/buckets/{bucketId}/backups/{backupId}/exports/{exportId}` | 200 | `status`; the download URL when complete. **New** |

## Design

### Commands
```
capellactl bucket backup list    CLUSTER [BUCKET]
capellactl bucket backup get     CLUSTER BACKUP_ID
capellactl bucket backup create  CLUSTER BUCKET
capellactl bucket backup delete  CLUSTER BACKUP_ID
capellactl bucket backup restore CLUSTER BACKUP_ID [--to-cluster NAME] [--services data,query]
                                 [--include-data B.S.C,…] [--exclude-data B.S.C,…] [--map-data SRC=DST,…]
                                 [--filter-keys REGEX] [--filter-values REGEX]
                                 [--replace-ttl none|all|expired] [--replace-ttl-with TIME]
                                 [--force-updates] [--auto-remove-collections]
capellactl bucket backup export  CLUSTER BACKUP_ID [--no-wait]
```
Shared flags: `--project`, global `--auto-approve`, `--no-wait`, `--timeout`, `-o json`.

Examples (safe defaults first):
```
capellactl bucket backup list nova-prod-01
capellactl bucket backup create nova-prod-01 orders
capellactl bucket backup restore nova-prod-01 7a2e… --replace-ttl none
capellactl bucket backup restore nova-prod-01 7a2e… --to-cluster nova-dr-01 --include-data orders.sales
capellactl bucket backup export nova-prod-01 7a2e…
```

- **list** (list layout, S.NO first, ID last): `S.NO  BUCKET  DATE  METHOD  SOURCE  STATUS  SIZE  ITEMS  EXPIRES
  ID`, newest first; `BUCKET` filters by bucket name.
- **create** waits until the backup is `ready` (or `failed`, exit 1) unless `--no-wait`. It is an action and writes
  nothing to capella.yaml.
- **delete** says that the whole cycle goes (`deletes cycle 2026-10-25 with 7 backups of orders`), asks for the
  bucket name to be typed (or `--auto-approve`).
- **restore** sends `sourceClusterID` = the backup's cluster and `targetClusterID` = `--to-cluster` or the same
  cluster, `services` default `data`. The plan lists what is restored and what is overwritten; `--force-updates`
  is shown as `overwrites newer data`. It asks for the target cluster's name to be typed, then waits until done.
- **export** starts the export, waits until it is complete and prints the download URL (a secret-like link: printed
  only to the terminal, never in logs, CAP-008). If the cycle already has an export (409), it prints that export's
  status and URL instead, exit 0, so re-runs are safe.

### Where the code goes
- `cli/bucket_backup.py` (from CAP-058).
- `api/endpoints.py`, fake Capella, refreshed responses file. The two export operations are in the spec snapshot
  since it was refreshed on 2026-10-29 with these stories.

## Acceptance criteria & tests

### AC1 — List and get
**Given** backups of two buckets, **then** `list CLUSTER` prints both in the list layout and `list CLUSTER orders`
only orders'; `get` prints one with its stats; `-o json` returns Capella's items; none → `no backups`, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac1_list` | `tests/scenario/test_bucket_backup.py` | Text, filter, JSON, empty |
| `test_bucket_backup_ac1_get` | same | |

### AC2 — Back up now
**Given** `create nova-dev-01 orders`, **then** one `POST …/buckets/{base64(orders)}/backups`, the tool waits until
`ready` and prints the ID; a `failed` backup exits 1 with Capella's status. An unknown bucket exits 1 before any
write. A free-tier cluster exits 4.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac2_create` | `tests/scenario/test_bucket_backup.py` | |
| `test_bucket_backup_ac2_create_failed_and_refused` | same | |

### AC3 — Delete a cycle
**Given** a backup, **then** `delete` names the cycle and its number of backups, asks for the typed bucket name and
sends one `DELETE`. **Given** an unknown ID, **then** `backup … not found`, exit 0 with `--auto-approve`, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac3_delete_cycle` | `tests/scenario/test_bucket_backup.py` | |
| `test_bucket_backup_ac3_delete_missing_noop` | same | |

### AC4 — Restore to the same cluster
**Given** `restore nova-dev-01 ID`, **then** one `POST …/restore` with `sourceClusterID` = `targetClusterID`,
`backupID`, `services: ["data"]` and no optional fields; the tool waits until it is done. A wrong typed name sends
nothing (exit 5).

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac4_restore_same_cluster` | `tests/scenario/test_bucket_backup.py` | Body, wait |
| `test_bucket_backup_ac4_restore_confirm` | same | |

### AC5 — Restore elsewhere or in part
**Given** `--to-cluster nova-dr-01 --include-data orders.sales --map-data orders=orders_copy --replace-ttl all
--replace-ttl-with 2027-01-01T00:00:00Z`, **then** the body carries the target cluster's ID and those fields as the
API names them. **Given** an unknown target cluster, `--replace-ttl-with` without `--replace-ttl all|expired`, or
`--services` outside `data,query`, **then** exit 3 with zero writes. **Given** a target that is `turnedOff`, exit 4.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac5_restore_options_body` | `tests/scenario/test_bucket_backup.py` | |
| `test_bucket_backup_ac5_restore_refused` | same | Parametrised |

### AC6 — Export
**Given** a `ready` backup of a complete cycle, **then** `export` sends one `POST …/export`, polls the export until
complete and prints the download URL only to the terminal (redaction canary, CAP-008). **Given** 409, **then** the
existing export is shown, exit 0, no further write. **Given** 422, **then** exit 4 with Capella's reason.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac6_export` | `tests/scenario/test_bucket_backup.py` | |
| `test_bucket_backup_ac6_export_existing_and_refused` | same | |

### AC7 — Discoverable
**Given** `bucket backup --help`, **then** every verb has an example; `docs/runbook.md` has "Restore a bucket from a
backup" and "Download a bucket backup".

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac7_help` | `tests/scenario/test_bucket_backup.py` | |

## Open questions
- `includeData`/`excludeData`/`mapData` are free strings in the spec; the format (`bucket.scope.collection`, comma
  separated, `src=dst`) is taken from `cbbackupmgr` and must be confirmed against the sandbox before AC5 is built.

## Implementation notes (as built)
- `capellactl/cli/bucket_backup.py`: `list`, `get`, `create`, `delete`, `restore`, `export`.
- `list CLUSTER` shows what Capella lists, the latest backup of each bucket; `list CLUSTER BUCKET` walks the bucket's
  cycles and shows every backup.
- **`create`**: the API answers 202 without an ID, so the command waits until the bucket's latest backup is a new one
  that is `ready` (exit 1 when it is `failed`), and prints its ID.
- **`restore` does not wait** (deviation from AC4): the Management API has no restore status for bucket backups, so
  the command says the restore started and that Capella reports its progress in the cluster's activity log.
- `restore` confirms with the target cluster's name; a wrong name prints `Cancelled` and exits 0 (the story's
  "exit 5" was wrong: 5 is the timeout code). An unknown `--to-cluster` exits 1 (`cluster … not found`), as every
  not-found cluster does, not 3. `includeData`, `excludeData`, `mapData`, `filterKeys` and `filterValues` are passed
  as given (the open question on their format stays open for the sandbox run).
- `delete` confirms with the bucket name and says how many backups the cycle has.
- **`export`**: on 409 Capella does not return the existing export's ID, so the command says the cycle already has an
  export and points to the new `--export-id ID` option, which shows an export's status and a fresh download link.
  422 exits 4 with Capella's reason. The link is printed to the terminal only: capellactl never logs response bodies.
- The two export operations were added to the spec snapshot (refreshed 2026-10-29), the endpoint inventory and the
  fake; the fake's backup responses match the spec (`test_fake_parity.py`).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_bucket_backup_ac1_list`, `test_bucket_backup_ac1_get` (tests/scenario/test_bucket_backup.py) |
| AC2 | `test_bucket_backup_ac2_create`, `test_bucket_backup_ac2_create_failed_and_refused` |
| AC3 | `test_bucket_backup_ac3_delete_cycle`, `test_bucket_backup_ac3_delete_missing_noop` |
| AC4 | `test_bucket_backup_ac4_restore_same_cluster`, `test_bucket_backup_ac4_restore_confirm` |
| AC5 | `test_bucket_backup_ac5_restore_options_body`, `test_bucket_backup_ac5_restore_refused`, `test_bucket_backup_ac5_restore_target_turned_off` |
| AC6 | `test_bucket_backup_ac6_export`, `test_bucket_backup_ac6_export_existing_and_refused` |
| AC7 | `test_bucket_backup_ac7_help` |
