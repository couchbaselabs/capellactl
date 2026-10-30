# CAP-084 — Operational Insights clusters

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E16 Operational Insights | P1 | 8 | CAP-009, CAP-007, CAP-019 | Not started |

## User story
As an **operator**, I want to create, resize, power and delete Operational Insights (columnar analytics) clusters
the same way I manage database clusters, so that analytics environments are code too.

## Context & discovery
Operational Insights clusters are a separate cluster type with their own endpoints and IDs (`analyticsClusterId`).

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Create | `POST …/projects/{p}/operationalInsightsClusters` | 202 | `name`, `description`, `cloudProvider` (`aws`, `gcp`), `region`, `nodes`, `compute` (`cpu`, `ram`), `availability.type`, `support` (`plan` `developer pro`/`enterprise`, `timezone`) → `id` |
| List (project) | `GET …/projects/{p}/operationalInsightsClusters` | 200 | |
| List (org) | `GET {org}/operationalInsightsClusters` | 200 | |
| Get | `GET …/operationalInsightsClusters/{id}` | 200 | `currentState` (`deploying`, `healthy`, `scaling`, `turnedOff`, …) |
| Update | `PUT …/operationalInsightsClusters/{id}` | 204 | `name`, `description`, `nodes`, `support` (all required); `If-Match` |
| Delete | `DELETE …/operationalInsightsClusters/{id}` | 202 | |
| Turn on | `POST …/{id}/activationState` | 202 | |
| Turn off | `DELETE …/{id}/activationState` | 202 | |

`compute`, `cloudProvider`, `region` and `availability` are immutable after create.

## Design

### Commands
```
capellactl insights list   [--project NAME | --all-projects]
capellactl insights get    NAME
capellactl insights create NAME --provider aws|gcp --region R --nodes N --compute CPUxRAM [--availability single|multi] [--support-plan P] [--timezone TZ]
capellactl insights update NAME [--nodes N] [--description TEXT] [--support-plan P] [--timezone TZ]
capellactl insights delete NAME
capellactl insights power on  NAME
capellactl insights power off NAME
```
Example:
```
capellactl insights create nova-insights --provider aws --region us-east-1 --nodes 2 --compute 4x32
```

### capella.yaml
```yaml
projects:
  - name: nova
    insightsClusters:
      - name: nova-insights
        cloudProvider: {type: aws, region: us-east-1}
        nodes: 2
        compute: {cpu: 4, ram: 32}
        availability: single
        support: {plan: developer pro, timezone: GMT}
```
- Follows the cluster patterns of 1.0.0: CAP-038 flow for CLI changes, CAP-007 waiter, CAP-012 immutable-field
  BLOCKED rows, CAP-013-style typed confirmation on delete, `PUT` with `If-Match`.
- `insights` clusters are project children in the dependency order, independent of database clusters.
- Code: `cli/insights_cmds.py`, `resources/insights_cluster.py`, eight operations, fake Capella state machine.

## Acceptance criteria & tests

### AC1 — Create
**Given** the example, **then** one `POST` with that body, a wait until `healthy`, capella.yaml updated, and `plan`
reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_ac1_create` | `tests/scenario/test_insights_clusters.py` | |

### AC2 — Idempotent
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_ac2_rerun_zero_writes` | `tests/scenario/test_insights_clusters.py` | |

### AC3 — Update and immutable fields
**Given** `nodes: 4`, **then** one `PUT` with the full required body and `If-Match`, then a wait until `healthy`.
**Given** a changed `compute` or region, **then** BLOCKED (exit 4).

| Test | Location | Verifies |
|---|---|---|
| `test_insights_ac3_update_nodes` | `tests/scenario/test_insights_clusters.py` | |
| `test_insights_ac3_immutable_blocked` | same | |

### AC4 — Power
**Given** `insights power off nova-insights`, **then** `DELETE …/activationState` and a wait until `turnedOff`;
`power on` reverses it; a turned-off cluster's other changes are DEFERRED.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_ac4_power` | `tests/scenario/test_insights_clusters.py` | |

### AC5 — Delete
**Given** `insights delete nova-insights`, **then** typed confirmation, one `DELETE`, a wait until gone, removal from
capella.yaml; a re-run prints `not found, nothing to do`.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_ac5_delete` | `tests/scenario/test_insights_clusters.py` | |

### AC6 — Lists, sync, drift, destroy
**Given** clusters, **then** `list` prints `S.NO`, `NAME`, `PROJECT`, `NODES`, `STATE`, `ID` (`--all-projects` uses
the org endpoint); `sync` writes them; `drift` lists unmanaged ones; `destroy` deletes them.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_ac6_list_sync_drift_destroy` | `tests/scenario/test_insights_clusters.py` | |

## Out of scope
- Linking an Operational Insights cluster to a database cluster's data (not in the Management API).

## Open questions
- Which `compute` sizes and node counts are allowed? Not enumerated in the spec; surface the API's 422 until known.
