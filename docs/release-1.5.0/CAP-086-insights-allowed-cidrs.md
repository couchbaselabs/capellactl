# CAP-086 — Operational Insights allowed CIDRs

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E16 Operational Insights | P1 | 2 | CAP-084, CAP-022 | Not started |

## User story
As an **operator**, I want to manage the IP allowlist of an Operational Insights cluster in capella.yaml, so that
only my networks can reach it.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| List | `GET …/operationalInsightsClusters/{id}/allowedcidrs` | 200 | |
| Create | `POST …/allowedcidrs` | 201 | `cidr`, `comment`, `expiresAt` |
| Get | `GET …/allowedcidrs/{allowedCidrId}` | 200 | |
| Delete | `DELETE …/allowedcidrs/{allowedCidrId}` | 204 | |

Same model as the database cluster's allowlist (CAP-022): no update, so a change is delete + create.

## Design
```
capellactl insights cidr list   NAME
capellactl insights cidr get    NAME CIDR
capellactl insights cidr create NAME CIDR [--comment TEXT] [--expires TIME]
capellactl insights cidr delete NAME CIDR
```
Example:
```
capellactl insights cidr create nova-insights 203.0.113.0/24 --comment office
```
```yaml
insightsClusters:
  - name: nova-insights
    allowedCidrs:
      - {cidr: 203.0.113.0/24, comment: office}
```
- Reuses CAP-022's reconciler with the Operational Insights endpoints (one parameterised class).
- `0.0.0.0/0` gets the same warning as in CAP-022.

## Acceptance criteria & tests

### AC1 — Create
**Given** the example, **then** one `POST` with `cidr` and `comment`, capella.yaml updated, and `plan` reports no
changes.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_cidr_ac1_create` | `tests/scenario/test_insights_cidrs.py` | |

### AC2 — Idempotent
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_cidr_ac2_rerun_zero_writes` | `tests/scenario/test_insights_cidrs.py` | |

### AC3 — Change is replace; delete
**Given** a changed comment, **then** `±` and delete + create. `cidr delete` asks once; re-run is a no-op.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_cidr_ac3_replace_delete` | `tests/scenario/test_insights_cidrs.py` | |

### AC4 — List, get, sync, drift
**Given** entries, **then** `list` prints `S.NO`, `CIDR`, `COMMENT`, `EXPIRES`, `ID`; `get` shows one entry; `sync`
writes them; `drift` lists unmanaged ones.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_cidr_ac4_list_get_sync_drift` | `tests/scenario/test_insights_cidrs.py` | |

## Out of scope
- None.

## Open questions
- None.
