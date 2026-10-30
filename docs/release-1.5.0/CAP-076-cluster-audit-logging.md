# CAP-076 — Cluster audit logging & exports

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E13 Private networking & security | P0 | 5 | CAP-011, CAP-038 | Not started |

## User story
As a **security engineer**, I want to turn on database audit logging with the events I care about and export the
logs for a time range, so that every environment meets our audit policy and I can hand logs to an auditor.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Get config | `GET …/clusters/{clusterId}/auditLog` | 200 | `auditEnabled`, `disabledUsers[]`, `enabledEventIDs[]` |
| Update config | `PUT …/clusters/{clusterId}/auditLog` | 204 | Same body; `auditEnabled` required |
| List events | `GET …/clusters/{clusterId}/auditLogEvents` | 200 | `events[]`: `id`, `name`, `module`, `description` |
| Create export | `POST …/clusters/{clusterId}/auditLogExports` | 202 | `start`, `end` (ISO 8601) → `exportId` |
| List exports | `GET …/clusters/{clusterId}/auditLogExports` | 200 | `auditLogExportId`, `start`, `end`, `status` (`Queued`, `In Progress`, `Completed`, `Failed`), `auditLogDownloadURL`, `expiration` |
| Get export | `GET …/auditLogExports/{auditLogExportId}` | 200 | |

## Design

### Commands
```
capellactl audit-log get    CLUSTER
capellactl audit-log update CLUSTER --enable|--disable [--event ID|NAME …] [--module M …] [--ignore-user NAME …]
capellactl audit-log events CLUSTER [--module M]
capellactl audit-log export create CLUSTER --from TIME --to TIME [--download DIR]
capellactl audit-log export list   CLUSTER
capellactl audit-log export get    CLUSTER EXPORT_ID [--download DIR]
```
Example:
```
capellactl audit-log events nova-prod-01 --module n1ql
capellactl audit-log update nova-prod-01 --enable --module n1ql
capellactl audit-log export create nova-prod-01 --from 2026-10-01 --to 2026-10-02 --download ./audit
```

### capella.yaml
```yaml
clusters:
  - name: nova-prod-01
    auditLog:
      enabled: true
      events: [n1ql]                 # event IDs, event names or module names
      ignoreUsers: [{name: orders_app, domain: local}]
```
- Names and modules are resolved to `enabledEventIDs` through `auditLogEvents`; the file keeps what the user wrote,
  and comparison is on the resolved ID set.
- `export create` waits until `Completed` (CAP-007) and, with `--download`, saves the file and prints its path; the
  download URL is never logged (it is a bearer link; CAP-008 redaction).
- Code: `cli/audit_log_cmds.py`, `resources/audit_log.py` (child of the cluster), six operations, fake Capella.

## Acceptance criteria & tests

### AC1 — Enable with events
**Given** `audit-log update nova-prod-01 --enable --module n1ql`, **then** one `PUT` with `auditEnabled: true` and the
IDs of the `n1ql` module's events, capella.yaml records it, and `plan` reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_audit_log_ac1_enable` | `tests/scenario/test_audit_log.py` | |

### AC2 — Idempotent
**Given** AC1 completed, **then** a re-run makes zero writes, even though the file names a module and Capella returns
IDs.

| Test | Location | Verifies |
|---|---|---|
| `test_audit_log_ac2_rerun_zero_writes` | `tests/scenario/test_audit_log.py` | |

### AC3 — Unknown events
**Given** an event or module that `auditLogEvents` does not list, **then** exit 3 with the closest names, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_audit_log_ac3_unknown_event` | `tests/scenario/test_audit_log.py` | |

### AC4 — Export
**Given** `export create` with `--from`/`--to`, **then** one `POST` with ISO 8601 times, a wait until `Completed`, and
with `--download` the file saved; the download URL appears in no output or log. `--to` before `--from`, or a range
the API refuses, exits 3.

| Test | Location | Verifies |
|---|---|---|
| `test_audit_log_ac4_export_and_download` | `tests/scenario/test_audit_log.py` | Includes `assert_no_secret` on the URL |
| `test_audit_log_ac4_bad_range` | same | |

### AC5 — Lists, sync, drift
**Given** exports, **then** `export list` prints `S.NO`, `FROM`, `TO`, `STATUS`, `EXPIRES`, `ID`; `events` prints
`S.NO`, `NAME`, `MODULE`, `ID`; `sync` writes `auditLog`; `drift` reports differences.

| Test | Location | Verifies |
|---|---|---|
| `test_audit_log_ac5_lists_sync_drift` | `tests/scenario/test_audit_log.py` | |

## Out of scope
- App Services audit logging (2.0.0).

## Open questions
- What is the maximum export range? The API's error is surfaced until it is known.
