# CAP-075 — Private endpoint service

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E13 Private networking & security | P0 | 5 | CAP-011, CAP-038 | Not started |

## User story
As an **operator**, I want to turn on a cluster's private endpoint service and accept my application's endpoints from
capellactl, so that traffic to the cluster never crosses the public internet.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Status | `GET …/clusters/{clusterId}/privateEndpointService` | 200 | `enabled`, `serviceName`, `status` (`idle`, `enabling`, `enabled`, `enableFailed`, `disabling`, `disabled`, `disableFailed`, `unknown`), `routes` |
| Enable | `POST …/privateEndpointService` | 202 | Optional `routes` (`xdcr`, `metrics`) |
| Update | `PUT …/privateEndpointService` | 202 | `routes` |
| Disable | `DELETE …/privateEndpointService` | 202 | |
| List endpoints | `GET …/privateEndpointService/endpoints` | 200 | `privateEndpointDNS`, `endpoints[]` (`id`, `serviceName`, `status`) |
| Endpoint command | `POST …/privateEndpointService/endpointCommand` | 200 | AWS `vpcID` + `subnetIDs`; Azure `resourceGroupName` + `virtualNetwork`; GCP `vpcNetworkID` + `subnetIDs` → `command` |
| Accept | `POST …/endpoints/{endpointId}/associate` | 204 | |
| Reject | `POST …/endpoints/{endpointId}/unassociate` | 204 | |

`routes.xdcr` lets XDCR (CAP-070) use the private endpoint and has node-count limits.

## Design

### Commands
```
capellactl private-endpoint show    CLUSTER
capellactl private-endpoint enable  CLUSTER [--xdcr] [--metrics]
capellactl private-endpoint update  CLUSTER [--xdcr on|off] [--metrics on|off]
capellactl private-endpoint disable CLUSTER
capellactl private-endpoint command CLUSTER (--vpc-id ID --subnet-id ID … | --resource-group RG --vnet NAME | --gcp-network ID --subnet-id ID …)
capellactl private-endpoint list    CLUSTER
capellactl private-endpoint accept  CLUSTER ENDPOINT_ID
capellactl private-endpoint reject  CLUSTER ENDPOINT_ID
```
Example:
```
capellactl private-endpoint enable nova-prod-01
capellactl private-endpoint command nova-prod-01 --vpc-id vpc-0a1b2c --subnet-id subnet-1 --subnet-id subnet-2
capellactl private-endpoint accept nova-prod-01 vpce-0123
```

### capella.yaml
```yaml
clusters:
  - name: nova-prod-01
    privateEndpointService:
      enabled: true
      routes: {xdcr: false, metrics: false}
      acceptedEndpoints: [vpce-0123]      # optional: apply accepts these when they appear
```
- `enable`, `update` and `disable` wait for a stable `status` (CAP-007). Enabling takes several minutes; the waiter's
  message says so.
- `disable` asks once and lists the linked endpoints that will stop working.
- Code: `cli/private_endpoint_cmds.py`, `resources/private_endpoint.py` (child of the cluster), eight operations,
  fake Capella.

## Acceptance criteria & tests

### AC1 — Enable
**Given** `private-endpoint enable nova-prod-01`, **then** one `POST`, a wait until `enabled`, capella.yaml records
`privateEndpointService.enabled: true`, and `plan` reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_private_endpoint_ac1_enable` | `tests/scenario/test_private_endpoints.py` | |

### AC2 — Idempotent
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_private_endpoint_ac2_rerun_zero_writes` | `tests/scenario/test_private_endpoints.py` | |

### AC3 — Routes
**Given** `routes.xdcr` changed, **then** one `PUT` with both routes and a wait. Enabling XDCR routes on a cluster
above the documented node limit is refused (exit 4).

| Test | Location | Verifies |
|---|---|---|
| `test_private_endpoint_ac3_routes` | `tests/scenario/test_private_endpoints.py` | |

### AC4 — Endpoints
**Given** a `pendingAcceptance` endpoint, **then** `list` prints `S.NO`, `SERVICE`, `STATUS`, `ID` and the DNS
name; `accept` associates it; `reject` asks once; an endpoint in `acceptedEndpoints` is accepted by `apply`.
`command` prints the cloud CLI command and refuses mixed provider flags (exit 3).

| Test | Location | Verifies |
|---|---|---|
| `test_private_endpoint_ac4_endpoints` | `tests/scenario/test_private_endpoints.py` | |

### AC5 — Disable
**Given** an enabled service, **then** `disable` lists linked endpoints, asks once, sends `DELETE` and waits until
`disabled`; on a protected cluster it is BLOCKED (exit 4).

| Test | Location | Verifies |
|---|---|---|
| `test_private_endpoint_ac5_disable` | `tests/scenario/test_private_endpoints.py` | |

### AC6 — sync and drift
**Given** the service enabled in Capella, **then** `sync` writes the block and `drift` reports differences.

| Test | Location | Verifies |
|---|---|---|
| `test_private_endpoint_ac6_sync_drift` | `tests/scenario/test_private_endpoints.py` | |

## Out of scope
- App Services and Operational Insights private endpoints (CAP-088; App Services in 2.0.0).

## Open questions
- Is a disable on a protected cluster refused by Capella, or should capellactl refuse it? AC5 refuses it locally.
