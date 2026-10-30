# CAP-088 — Operational Insights private endpoints

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E16 Operational Insights | P2 | 3 | CAP-084, CAP-075 | Not started |

## User story
As an **operator**, I want private endpoints for my Operational Insights cluster, so that analytics traffic stays off
the public internet like my database traffic does.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Status | `GET …/operationalInsightsClusters/{id}/privateEndpointService` | 200 | `enabled` |
| Enable | `POST …/privateEndpointService` | 202 | |
| Disable | `DELETE …/privateEndpointService` | 202 | |
| Endpoint command | `POST …/privateEndpointService/endpointCommand` | 200 | Cloud-specific body → `command` |
| List endpoints | `GET …/privateEndpointService/endpoints` | 200 | |
| Accept | `POST …/endpoints/{endpointId}/associate` | 204 | |
| Reject | `POST …/endpoints/{endpointId}/unassociate` | 204 | |

The same flow as the database cluster's service (CAP-075) without `routes` or update.

## Design
```
capellactl insights private-endpoint show    NAME
capellactl insights private-endpoint enable  NAME
capellactl insights private-endpoint disable NAME
capellactl insights private-endpoint command NAME (cloud flags as CAP-075)
capellactl insights private-endpoint list    NAME
capellactl insights private-endpoint accept  NAME ENDPOINT_ID
capellactl insights private-endpoint reject  NAME ENDPOINT_ID
```
```yaml
insightsClusters:
  - name: nova-insights
    privateEndpointService: {enabled: true, acceptedEndpoints: [vpce-0456]}
```
- Reuses CAP-075's reconciler and commands, parameterised on the endpoint family.

## Acceptance criteria & tests

### AC1 — Enable
**Given** `insights private-endpoint enable nova-insights`, **then** one `POST`, a wait until enabled, the block in
capella.yaml, and a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_pe_ac1_enable` | `tests/scenario/test_insights_private_endpoints.py` | |
| `test_insights_pe_ac1_rerun_zero_writes` | same | |

### AC2 — Endpoints
**Given** a pending endpoint, **then** `list`, `accept`, `reject` and `command` behave as CAP-075 AC4.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_pe_ac2_endpoints` | `tests/scenario/test_insights_private_endpoints.py` | |

### AC3 — Disable
**Given** an enabled service, **then** `disable` lists linked endpoints, asks once, sends `DELETE` and waits.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_pe_ac3_disable` | `tests/scenario/test_insights_private_endpoints.py` | |

### AC4 — sync and drift
**Given** the service enabled in Capella, **then** `sync` writes the block and `drift` reports differences.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_pe_ac4_sync_drift` | `tests/scenario/test_insights_private_endpoints.py` | |

## Out of scope
- None.

## Open questions
- None.
