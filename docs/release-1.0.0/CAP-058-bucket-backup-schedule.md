# CAP-058 — Bucket backup schedule as code, and backup cycles

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E10 Backup & restore | P1 | 5 | CAP-023, CAP-056 | Implemented |

## User story
As an **operator**, I want to set a weekly full + incremental backup schedule per bucket, with one command or in
capella.yaml, and see the backup cycles it has produced, so that each bucket is backed up on its own terms.

## Context & discovery
- The bucket half of the customer request in CAP-056. A bucket backup is per bucket: one **full** backup a week
  starts a **cycle**, followed by **incrementals** every few hours.

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Get schedule | `GET …/buckets/{bucketId}/backup/schedules` | 200 | `type: weekly`, `weeklySchedule` |
| Create schedule | `POST …/buckets/{bucketId}/backup/schedules` | 202 | |
| Update schedule | `PUT …/buckets/{bucketId}/backup/schedules` | 202 | |
| Delete schedule | `DELETE …/buckets/{bucketId}/backup/schedules` | 202 | |
| List cycles | `GET …/buckets/{bucketId}/backup/cycles` | 200 | |
| Backups of a cycle | `GET …/buckets/{bucketId}/backup/cycles/{cycleId}` | 200 | |

`weeklySchedule` (all required), enums from the spec:

| Field | Values | Flag |
|---|---|---|
| `dayOfWeek` | `sunday` … `saturday` | `--day` |
| `startAt` | hour 0–23 | `--start-at` |
| `incrementalEvery` | 1, 2, 4, 6, 8, 12, 24 (hours) | `--incremental-every` |
| `retentionTime` | `30days`, `60days`, `90days`, `180days`, `1year`, `2years`, `3years`, `4years`, `5years` | `--retention` |
| `costOptimizedRetention` | boolean | `--cost-optimized/--no-cost-optimized` |

`bucketId` is the Base64 of the bucket name, as the bucket commands already compute.

## Design

### Commands
```
capellactl bucket backup schedule show   CLUSTER BUCKET
capellactl bucket backup schedule set    CLUSTER BUCKET [--day D] [--start-at H] [--incremental-every H]
                                                        [--retention R] [--cost-optimized/--no-cost-optimized]
capellactl bucket backup schedule delete CLUSTER BUCKET
capellactl bucket backup cycle list      CLUSTER BUCKET
capellactl bucket backup cycle get       CLUSTER BUCKET CYCLE_ID
```
Arguments as the other bucket commands (`bucket create CLUSTER NAME`); shared flags `--project`, `--no-apply`,
global `--auto-approve`, `-o json`.

Examples (defaults first):
```
capellactl bucket backup schedule set nova-prod-01 orders
capellactl bucket backup schedule set nova-prod-01 orders --day sunday --start-at 2 --incremental-every 12 --retention 30days
capellactl bucket backup cycle list nova-prod-01 orders
```

- `set` without options uses `sunday`, `0`, `24`, `30days`, `--no-cost-optimized`; interactive terminals are asked
  each value with those defaults. An existing schedule is kept for values not given. It sends `POST` when no schedule
  exists and `PUT` otherwise.
- **show**: `weekly full on sunday at 00:00 UTC · incremental every 24 h · kept 30 days`, `no backup schedule` when
  none.
- **cycle list** (list layout, S.NO first, ID last): `S.NO  STARTED  BACKUPS  STATUS  ID`. **cycle get** lists the
  backups of one cycle: `S.NO  DATE  METHOD  SOURCE  STATUS  SIZE  ITEMS  EXPIRES  ID`.

### capella.yaml
```yaml
buckets:
  - name: orders
    backupSchedule:            # bucket backups: weekly full + incrementals
      type: weekly
      weeklySchedule:
        dayOfWeek: sunday
        startAt: 0
        incrementalEvery: 24
        retentionTime: 30days
        costOptimizedRetention: false
```
Reconciled as a child of the bucket, like the cluster schedule in CAP-056 (plan, apply, sync, drift, prune).

### Where the code goes
- `cli/bucket_backup.py` (new): the `bucket backup` sub-group, registered in `bucket_cmds.py`.
- `resources/bucket_backup_schedule.py` (new); schema, `help config`, `make docs`.

## Acceptance criteria & tests

### AC1 — Set a schedule
**Given** `bucket backup schedule set nova-dev-01 orders`, **then** one `POST …/backup/schedules` is sent with the
defaults, capella.yaml records `backupSchedule` under the bucket, and a later `plan` reports no changes. **Given** a
schedule exists and `--incremental-every 12`, **then** one `PUT` with only that value changed.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac1_set_create` | `tests/scenario/test_bucket_backup_schedule.py` | POST body, file |
| `test_bucket_backup_ac1_set_update` | same | PUT body |

### AC2 — Idempotent
**Given** AC1 completed, **when** the command or `apply` runs again, **then** `no changes`, exit 0, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac2_rerun_zero_writes` | `tests/scenario/test_bucket_backup_schedule.py` | |

### AC3 — Invalid values refused offline
**Given** a value outside the enums above (for example `--incremental-every 3` or `--retention 45days`), **then**
`validate` and the command exit 3 listing the allowed values, with zero API calls. **Given** a bucket on a free-tier
cluster, **then** exit 4.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac3_invalid_values` | `tests/scenario/test_bucket_backup_schedule.py` | Parametrised |
| `test_bucket_backup_ac3_free_tier` | same | |

### AC4 — Show and delete
**Given** a schedule, **then** `show` prints it and `-o json` returns Capella's body; `delete` asks once, sends one
`DELETE` and removes the block from capella.yaml. **Given** none, both print `no backup schedule`, exit 0, zero
writes.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac4_show` | `tests/scenario/test_bucket_backup_schedule.py` | |
| `test_bucket_backup_ac4_delete_and_missing` | same | |

### AC5 — Cycles
**Given** two cycles, **then** `cycle list` prints them in the list layout; `cycle get` lists the cycle's backups
with method (full/incremental), source (scheduled/manual) and status.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac5_cycles` | `tests/scenario/test_bucket_backup_schedule.py` | |

### AC6 — In the environment commands
**Given** `backupSchedule` under a bucket, **then** `apply` creates it after the bucket; `sync` writes it from
Capella; `drift` reports a changed or unmanaged schedule; `apply --prune` deletes an unmanaged one; `destroy` needs no
extra step (the bucket's deletion removes it).

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac6_apply_sync_drift` | `tests/scenario/test_bucket_backup_schedule.py` | |

### AC7 — Discoverable
**Given** `bucket backup --help`, **then** every verb has an example; `help backup` (CAP-056) covers bucket backups;
`docs/runbook.md` has "Set a bucket backup schedule".

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_backup_ac7_help` | `tests/scenario/test_bucket_backup_schedule.py` | |

## Open questions
- Do `POST`/`PUT` of a schedule finish synchronously in practice despite the `202`? If not, the command waits until
  `GET` returns the new values.

## Implementation notes (as built)
- `capellactl/cli/bucket_backup.py`: the `bucket backup` sub-group with `schedule show|set|delete` and
  `cycle list|get`, registered on the `bucket` group.
- **capella.yaml form:** the schedule is written flat under the bucket (`dayOfWeek`, `startAt`, `incrementalEvery`,
  `retentionTime`, `costOptimizedRetention`), not as `type: weekly` + `weeklySchedule:`; `weekly` is the only type the
  API has, so it is implied. Missing fields take the defaults (Sunday, 0, 24, 30days, false); `set` and `sync` write
  all five. The schedule goes before the bucket's `scopes`.
- `BucketBackupScheduleReconciler` (kind `bucket-backup-schedule`, a child of the bucket): `POST` when there is no
  schedule, `PUT` otherwise; read only when declared, as CAP-056 (a 403 or 404 counts as none). `drift` lists an
  undeclared schedule and `apply --prune` deletes it; `sync` writes it, or keeps the file's when it cannot be read.
- AC3: the enums are in `config/schema.json`, so an invalid value exits 3 from validation with zero API calls.
- Interactive terminals are asked each value when a new schedule is set without options.
- Open question (POST/PUT answer 202): the fake applies them at once; if Capella does not, the next `plan` shows the
  difference and `apply` repeats the write. To be confirmed on the sandbox.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_bucket_backup_ac1_set_create`, `test_bucket_backup_ac1_set_update`, `test_bucket_backup_ac1_set_interactive` (tests/scenario/test_bucket_backup_schedule.py) |
| AC2 | `test_bucket_backup_ac2_rerun_zero_writes` |
| AC3 | `test_bucket_backup_ac3_invalid_values`, `test_bucket_backup_ac3_free_tier` |
| AC4 | `test_bucket_backup_ac4_show`, `test_bucket_backup_ac4_delete_and_missing` |
| AC5 | `test_bucket_backup_ac5_cycles` |
| AC6 | `test_bucket_backup_ac6_apply_sync_drift` |
| AC7 | `test_bucket_backup_ac7_help` |
