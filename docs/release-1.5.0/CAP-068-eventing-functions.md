# CAP-068 — Eventing functions as code

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E11 Data access & tools | P1 | 8 | CAP-025 | Not started |

## User story
As a **developer**, I want to keep my Eventing functions' JavaScript and settings in my repository and deploy them
with `apply`, so that function code is reviewed, versioned and identical in every environment.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| List | `GET …/clusters/{clusterId}/eventingFunctions` | 200 | Paginated; filter by status |
| Create | `POST …/clusters/{clusterId}/eventingFunctions` | 201 | `name`, `description`, `code`, `eventSource`, `eventMetadataStorage` (keyspaces), `settings`, `bindings` |
| Get | `GET …/eventingFunctions/{functionName}` | 200 | `status`: `deployed`, `undeployed`, `paused`, `deploying`, `undeploying`, `pausing` |
| Update | `PUT …/eventingFunctions/{functionName}` | 204 | Full definition |
| Delete | `DELETE …/eventingFunctions/{functionName}` | 204 | Must be undeployed |
| Get code | `GET …/eventingFunctions/{functionName}/code` | 200 | JavaScript as text |
| Set code | `PUT …/eventingFunctions/{functionName}/code` | 204 | JavaScript as text |
| Set state | `PUT …/eventingFunctions/{functionName}/activationState` | 204 | `state`: `deploy`, `undeploy`, `pause`, `resume` |
| Logs | `GET …/eventingFunctions/{functionName}/logs` | 200 | Text |

`settings`: `workerCount`, `scriptTimeout`, `sqlConsistency` (`none`, `request`), `languageCompatibility`,
`feedBoundary` (`everything`, `from_now`), `maxTimerContextSize`, `allowSyncDocuments`, `cursorAware`. `bindings`:
`buckets[]` (`alias`, `bucket`, `scope`, `collection`, `permission` `read`/`readWrite`), `urls[]`, `constants[]`.
URL binding credentials are secrets (`${env:…}` references only, CAP-002). The cluster needs the eventing service.

## Design

### Commands
```
capellactl eventing list   CLUSTER
capellactl eventing get    CLUSTER NAME [--export]
capellactl eventing create CLUSTER NAME --source B.S.C --metadata B.S.C --code FILE [--binding ALIAS=B.S.C[:rw] …] [--feed-boundary everything|from_now]
capellactl eventing update CLUSTER NAME [--code FILE] [--binding …] [--description TEXT]
capellactl eventing delete CLUSTER NAME
capellactl eventing code get CLUSTER NAME [--out FILE]
capellactl eventing code set CLUSTER NAME FILE
capellactl eventing state  CLUSTER NAME deploy|undeploy|pause|resume
capellactl eventing logs   CLUSTER NAME
```
Example:
```
capellactl eventing create nova-dev-01 audit-trail --source orders.sales.orders --metadata eventing.meta.store --code functions/audit-trail.js
capellactl eventing state nova-dev-01 audit-trail deploy
```

### capella.yaml
```yaml
clusters:
  - name: nova-dev-01
    eventingFunctions:
      - name: audit-trail
        code: functions/audit-trail.js       # path relative to capella.yaml
        eventSource: orders.sales.orders
        eventMetadataStorage: eventing.meta.store
        state: deployed                     # deployed | undeployed | paused
        settings: {feedBoundary: from_now}
        bindings:
          buckets: [{alias: audit, bucket: orders, scope: sales, collection: audit, permission: readWrite}]
```
- The code is compared byte for byte (line endings normalised). A changed definition of a deployed function is
  applied as `pause → update → resume` when Capella allows it, otherwise `undeploy → update → deploy`; `plan` says
  which and warns that `undeploy` loses the feed position unless `feedBoundary` is `from_now`.
- Functions reconcile after the keyspaces they reference.
- Code: `cli/eventing_cmds.py`, `resources/eventing_function.py` (prunable), nine operations, fake Capella with the
  state machine above.

## Acceptance criteria & tests

### AC1 — Create and deploy from capella.yaml
**Given** a declared function with `state: deployed`, **then** `apply` sends `POST` with the file's code and
`PUT …/activationState {state: deploy}`, waits until `deployed`, and `plan` reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_eventing_ac1_apply_create_deploy` | `tests/scenario/test_eventing.py` | |

### AC2 — Idempotent
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_eventing_ac2_rerun_zero_writes` | `tests/scenario/test_eventing.py` | |

### AC3 — Code change on a deployed function
**Given** the JavaScript file changed, **then** `plan` shows `~ eventing function nova-dev-01/audit-trail  code
changed (+12 −3 lines)` and the pause/resume path, and `apply` follows it.

| Test | Location | Verifies |
|---|---|---|
| `test_eventing_ac3_code_change_pause_resume` | `tests/scenario/test_eventing.py` | |
| `test_eventing_ac3_definition_change_undeploy_redeploy` | same | |

### AC4 — Validation before any write
**Given** a missing code file, a keyspace not in capella.yaml or Capella, `eventSource` equal to
`eventMetadataStorage`, or a URL binding password written in plain text, **then** exit 3 with the field, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_eventing_ac4_validation` | `tests/unit/config/test_eventing_rules.py` | Parametrised |

### AC5 — Commands
**Given** the commands above, **then** `list` prints `S.NO`, `NAME`, `STATUS`, `SOURCE`; `code get` writes the code;
`state` waits for the target status; `logs` prints the function log; `delete` undeploys first after one
confirmation.

| Test | Location | Verifies |
|---|---|---|
| `test_eventing_ac5_commands` | `tests/scenario/test_eventing.py` | |

### AC6 — sync, drift, prune
**Given** functions in Capella, **then** `sync` writes each definition and saves the code to
`functions/<name>.js` (never overwriting a changed local file without `--force`); `drift` reports code and state
differences; `apply --prune` undeploys and deletes unmanaged functions.

| Test | Location | Verifies |
|---|---|---|
| `test_eventing_ac6_sync_drift_prune` | `tests/scenario/test_eventing.py` | |

## Out of scope
- Eventing function debugging and timers inspection; the API has no operations for them.

## Open questions
- Does `PUT …/eventingFunctions/{name}` accept a change while the function is paused, or only when undeployed?
