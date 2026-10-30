# CAP-087 — Operational Insights snapshot backups & schedule

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E16 Operational Insights | P2 | 5 | CAP-084, CAP-056, CAP-057 | Not started |

## User story
As an **operator**, I want to schedule, take and restore snapshot backups of an Operational Insights cluster, so
that analytics data is protected the same way as my database clusters.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Create backup | `POST …/operationalInsightsClusters/{id}/cloudSnapshotBackups` | 202 | Optional `retention` (hours) → `backupId` |
| List backups | `GET …/cloudSnapshotBackups` | 200 | `id`, `createdAt`, `type`, `retention`, `expiration`, `progress`, `region`, `databaseSize` |
| Update retention | `PUT …/cloudSnapshotBackups/{backupId}` | 204 | `retention` |
| Delete backup | `DELETE …/cloudSnapshotBackups/{backupId}` | 204 | |
| Restore | `POST …/cloudSnapshotBackups/{backupId}/restore` | 202 | → `restoreId` |
| List restores | `GET …/cloudSnapshotBackups/restores` | 200 | `status`, `restoreTo`, `snapshot` |
| Get schedule | `GET …/cloudSnapshotBackupSchedule` | 200 / 204 | `interval`, `retention`, `startTime`; 204 when none |
| Upsert schedule | `PUT …/cloudSnapshotBackupSchedule` | 204 | All three required |
| Delete schedule | `DELETE …/cloudSnapshotBackupSchedule` | 204 | |

Unlike the database cluster (CAP-056), there is no schedule options endpoint and no copy-to-region.

## Design
```
capellactl insights backup list     NAME
capellactl insights backup create   NAME [--retain DURATION]
capellactl insights backup retain   NAME BACKUP_ID DURATION
capellactl insights backup delete   NAME BACKUP_ID
capellactl insights backup restore  NAME BACKUP_ID
capellactl insights backup restores NAME
capellactl insights backup schedule show   NAME
capellactl insights backup schedule set    NAME --every HOURS --retain DURATION --start HH:MM
capellactl insights backup schedule delete NAME
```
Example:
```
capellactl insights backup schedule set nova-insights --every 24 --retain 7d --start 02:00
```
```yaml
insightsClusters:
  - name: nova-insights
    backupSchedule: {interval: 24, retention: 168, startTime: "02:00"}
```
- Reuses the CAP-056/CAP-057 code: duration parsing, `startTime` as UTC time of day, list columns, the restore
  confirmation (typed cluster name; it overwrites the cluster's data) and the waiter.
- Code: `cli/insights_backup.py`, `resources/insights_backup_schedule.py`, nine operations, fake Capella.

## Acceptance criteria & tests

### AC1 — Schedule as code
**Given** the example, **then** one `PUT` with `interval: 24, retention: 168` and the next 02:00 UTC, capella.yaml
records it, and a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_backup_ac1_schedule_set` | `tests/scenario/test_insights_backups.py` | |
| `test_insights_backup_ac1_rerun_zero_writes` | same | |

### AC2 — Back up now and retain
**Given** `backup create nova-insights --retain 3d`, **then** one `POST` with `retention: 72` and a wait until the
backup completes; `retain` sends one `PUT`.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_backup_ac2_create_retain` | `tests/scenario/test_insights_backups.py` | |

### AC3 — Restore
**Given** `backup restore nova-insights ID`, **then** typed confirmation, one `POST …/restore`, a wait until the
restore completes; `restores` lists it.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_backup_ac3_restore` | `tests/scenario/test_insights_backups.py` | |

### AC4 — Lists, delete, schedule show/delete
**Given** backups, **then** `list` prints `S.NO`, `CREATED`, `TYPE`, `SIZE`, `EXPIRES`, `ID`; `delete` asks once;
`schedule show` prints the schedule or `no backup schedule` (204); `schedule delete` removes it and the block.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_backup_ac4_lists_and_deletes` | `tests/scenario/test_insights_backups.py` | |

### AC5 — sync, drift, prune
**Given** a schedule in Capella, **then** `sync` writes it, `drift` reports an unmanaged one, and `apply --prune`
deletes it (read only when declared, as CAP-056).

| Test | Location | Verifies |
|---|---|---|
| `test_insights_backup_ac5_sync_drift_prune` | `tests/scenario/test_insights_backups.py` | |

## Out of scope
- Restoring into another Operational Insights cluster (not in the API).

## Open questions
- Which intervals and retentions are allowed without an options endpoint? Surface the API's error until known.
