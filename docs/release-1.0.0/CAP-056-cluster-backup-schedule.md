# CAP-056 — Cluster backup schedule (cloud snapshots) as code

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E10 Backup & restore | P1 | 5 | CAP-011, CAP-020, CAP-038 | Implemented |

## User story
As an **operator**, I want to set how often a cluster is backed up and how long each backup is kept, with one
command or in capella.yaml, so that every cluster I deploy is protected without opening the Capella UI.

## Context & discovery
- Requested by a customer (2026-10-29): backup and restore from capellactl, with a schedule for **cluster** backups
  and, separately, for **bucket** backups (CAP-058), and list commands that look like every other list.
- Capella has two backup kinds. **Cloud snapshot backups** copy the whole cluster (every bucket, index and
  setting) at the cloud-disk level; this story and CAP-057 cover them as `cluster backup …`. **Bucket backups**
  are per bucket, full + incremental; CAP-058 and CAP-059 cover them as `bucket backup …`.
- 00-architecture.md §14 listed backup schedules under "Not in 1.0.0"; this story moves them into 1.0.0.

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Get schedule | `GET …/clusters/{clusterId}/cloudsnapshotbackupschedule` | 200 | `interval`, `retention` (hours), `startTime` (ISO 8601), `copyToRegions` |
| Upsert schedule | `PUT …/clusters/{clusterId}/cloudsnapshotbackupschedule` | 204 | Same body; creates or replaces |
| Delete schedule | `DELETE …/clusters/{clusterId}/cloudsnapshotbackupschedule` | 204 | |
| Schedule options | `GET …/clusters/{clusterId}/cloudsnapshotbackupschedule/options` | 200 | `intervals` (hours), `minimumRetention`, `maximumRetention` (hours) the cluster's support plan permits. **New in the spec after the 2026-10-06 snapshot** |
| Copy regions | `GET …/clusters/{clusterId}/cloudsnapshotbackups/regions` | 200 | Regions a copy can go to (shared with CAP-057) |

The permitted intervals and retention change with the support plan ("read this endpoint before creating or
updating a backup schedule"), so they are read from Capella, never hard-coded. Free-tier clusters have no backups
(`FREE_TIER_MISSING`).

## Design

### Commands
```
capellactl cluster backup schedule show    NAME
capellactl cluster backup schedule options NAME
capellactl cluster backup schedule set     NAME --every HOURS --retain DURATION [--start HH:MM] [--copy-to REGION …]
capellactl cluster backup schedule delete  NAME
```
Shared flags as for every cluster command: `--project`, `--no-apply`, global `--auto-approve`, `-o json`.

Examples:
```
capellactl cluster backup schedule options nova-prod-01
capellactl cluster backup schedule set nova-prod-01 --every 24 --retain 30d
capellactl cluster backup schedule set nova-prod-01 --every 6 --retain 7d --start 02:00 --copy-to us-west-2
capellactl cluster backup schedule show nova-prod-01
```

- `cluster backup` is a new sub-group of `cluster`, like `cluster schedule` and `cluster group`; `schedule` is its
  sub-group. `set` and `delete` follow the CAP-038 flow: change the entry → validate → plan → confirm → write → apply.
- `--retain` takes hours or days (`168`, `168h`, `7d`) and is sent as hours. `--start` is the time of day in UTC for
  the first backup, sent as the next such instant in ISO 8601. `--copy-to` may repeat; at most two regions (the
  same limit as on-demand backups).
- **show** prints the schedule as stored in Capella: `every 24 h · kept 30 days · first at 02:00 UTC · copies:
  us-west-2`, then the next backup time; `no backup schedule` when none.
- **options** prints the permitted intervals and retention range for the cluster's support plan, and the copy regions.

### capella.yaml
```yaml
clusters:
  - name: nova-prod-01
    backupSchedule:          # cloud snapshot backups of the whole cluster
      interval: 24           # hours, one of the plan's intervals
      retention: 720         # hours
      startTime: "02:00"     # UTC
      copyToRegions: [us-west-2]
```
Field names follow the API (`x-api` in the schema). `plan`, `apply`, `drift`, `sync` and `destroy` treat it like
the hibernation schedule (CAP-020): a missing block in the file with a schedule in Capella is reported by `drift` as
unmanaged and removed only by `apply --prune`.

### Plan output
```
~ cluster nova-prod-01   backup schedule
  + every 24 h · kept 30 days · first at 02:00 UTC · copies: us-west-2
```

### Where the code goes
- `cli/cluster_backup.py` (new): the `backup` sub-group with `schedule show|options|set|delete`.
- `resources/backup_schedule.py` (new): reconciler, child of the cluster in the dependency order (§4.2).
- `api/endpoints.py`: the four operations; `docs/api/management-api-v4.0-responses.json` refreshed and the fake
  Capella extended until `test_fake_parity.py` passes.

## Acceptance criteria & tests

### AC1 — Set a schedule
**Given** `cluster backup schedule set nova-dev-01 --every 24 --retain 30d`, **then** the options endpoint is read,
one `PUT …/cloudsnapshotbackupschedule` is sent with `interval: 24, retention: 720`, capella.yaml records
`backupSchedule`, and a later `plan` reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac1_set_body` | `tests/scenario/test_cluster_backup_schedule.py` | PUT body, file |
| `test_cluster_backup_ac1_no_drift` | same | |

### AC2 — Idempotent
**Given** AC1 completed, **when** the same command or `apply` runs again, **then** `no changes`, exit 0, zero
`POST`/`PUT`/`DELETE` calls.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac2_rerun_zero_writes` | `tests/scenario/test_cluster_backup_schedule.py` | |

### AC3 — Values the plan does not permit are refused before any write
**Given** an interval not in `intervals`, or a retention outside `minimumRetention`–`maximumRetention`, or more
than two `--copy-to` regions, or a region not in the regions list, **then** exit 3 with the permitted values
(`--every must be one of 1, 2, 4, 6, 8, 12, 24 for this cluster's support plan`) and zero writes. **Given** a
free-tier cluster, **then** exit 4 `free-tier clusters have no backups`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac3_refused` | `tests/scenario/test_cluster_backup_schedule.py` | Parametrised |
| `test_cluster_backup_ac3_free_tier` | same | |

### AC4 — Show and options
**Given** a schedule exists, **then** `show` prints it with the next backup time and `-o json` returns Capella's
body; **given** none, `no backup schedule`, exit 0. `options` prints the permitted intervals, retention range and
copy regions.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac4_show` | `tests/scenario/test_cluster_backup_schedule.py` | Text, JSON, none |
| `test_cluster_backup_ac4_options` | same | |

### AC5 — Delete
**Given** a schedule, **then** `delete` shows `- backup schedule`, asks once, sends one `DELETE` and removes
`backupSchedule` from capella.yaml. **Given** none, **then** `no backup schedule`, exit 0, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac5_delete` | `tests/scenario/test_cluster_backup_schedule.py` | |
| `test_cluster_backup_ac5_delete_missing_noop` | same | |

### AC6 — In the environment commands
**Given** `backupSchedule` in capella.yaml, **then** `plan`/`apply` create or update it after the cluster is
healthy; `sync` writes it from Capella; `drift` reports a changed or unmanaged schedule; `apply --prune` deletes an
unmanaged one.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac6_apply_creates` | `tests/scenario/test_cluster_backup_schedule.py` | |
| `test_cluster_backup_ac6_sync_round_trip` | same | |
| `test_cluster_backup_ac6_drift_and_prune` | same | |

### AC7 — Discoverable
**Given** `cluster backup schedule --help`, **then** every verb has an example. `help backup` explains cluster
versus bucket backups, `capellactl help config clusters.backupSchedule` describes the block, and `docs/runbook.md`
has "Set a cluster backup schedule".

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_backup_ac7_help` | `tests/scenario/test_cluster_backup_schedule.py` | |

## Out of scope
- Operational Insights cluster snapshots (`…/operationalInsightsClusters/{id}/cloudSnapshotBackupSchedule`): not an
  operational-database cluster.

## Open questions
- Does Capella create a default snapshot schedule for a new cluster? If so, `sync` after `cluster create` records it
  and `plan` must not report it as drift.

## Implementation notes (as built)
- `capellactl/cli/cluster_backup.py`: the `cluster backup` sub-group and its `schedule` group (`show`, `options`,
  `set`, `delete`). `set` also takes `--no-copies` (stop keeping copies) and changes only the values given on an
  existing schedule. It reads the options (and the copy regions, when `--copy-to` is given) before anything is
  written, so a value the support plan does not permit exits 3 with the permitted values (AC3).
- `capellactl/resources/backup_schedule.py`: `ClusterBackupScheduleReconciler` (kind `backup-schedule`), a child of
  the cluster after the hibernation schedule. A plan or apply with a value outside the options is BLOCKED (exit 4)
  with the same message.
- **Read only when declared.** Most backup endpoints need an Organization Owner or Project Owner key (spec), so the
  reconciler is prunable but does not report unmanaged schedules on `plan` (unlike the hibernation schedule):
  `plan` and `apply` read it only when the file has `backupSchedule`; `drift` lists an undeclared one and
  `apply --prune` deletes it. A 403 or 404 on the read counts as "no schedule". This keeps plans made with a Project
  Manager key working, and also answers the open question: a schedule Capella may create by default is not drift.
- The API returns **204** (no body) when there is no schedule; `get_snapshot_schedule` returns None for it.
- `startTime` is stored as the UTC time of day (`"02:00"`), sent as the next such instant, and compared by time of
  day, so re-runs stay idempotent.
- `sync` reads the schedule of running, provisioned clusters. For a turned-off cluster, or when the key may not read
  backups (403), it keeps the file's `backupSchedule` (as CAP-054 does for buckets) and warns once.
- `GET …/cloudsnapshotbackupschedule/options` was added to the offline spec snapshot (refreshed 2026-10-29) and to
  the fake; `docs/api/management-api-v4.0-responses.json` refreshed; `help backup` is a new topic.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_cluster_backup_ac1_set_body`, `test_cluster_backup_ac1_no_drift` (tests/scenario/test_cluster_backup_schedule.py) |
| AC2 | `test_cluster_backup_ac2_rerun_zero_writes` |
| AC3 | `test_cluster_backup_ac3_refused`, `test_cluster_backup_ac3_free_tier` |
| AC4 | `test_cluster_backup_ac4_show`, `test_cluster_backup_ac4_options` |
| AC5 | `test_cluster_backup_ac5_delete`, `test_cluster_backup_ac5_delete_missing_noop` |
| AC6 | `test_cluster_backup_ac6_apply_creates`, `test_cluster_backup_ac6_sync_round_trip`, `test_cluster_backup_ac6_sync_keeps_schedule_the_key_cannot_read`, `test_cluster_backup_ac6_drift_and_prune` |
| AC7 | `test_cluster_backup_ac7_help` |
