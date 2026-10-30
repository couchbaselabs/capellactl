# CAP-069 — Data API

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E11 Data access & tools | P1 | 5 | CAP-011, CAP-038 | Not started |

## User story
As a **developer**, I want to turn on a cluster's Data API (HTTP access to documents) and its private endpoints from
capellactl, so that serverless functions and tools without an SDK can reach the data.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Get status | `GET …/clusters/{clusterId}/dataAPI` | 200 | `enabled`, `state` (`enabled`, `disabled`, `enabling`, `disabling`, `configuring`), `enabledForNetworkPeering`, `stateForNetworkPeering`, `connectionString` |
| Update | `PUT …/clusters/{clusterId}/dataAPI` | 202 | `enableDataApi`, `enableNetworkPeering` (both required) |
| Endpoint command | `POST …/dataAPI/privateEndpointCommand` | 200 | AWS `vpcID` + `subnetIDs`, or Azure `resourceGroupName` + `virtualNetwork` → `command` |
| List endpoints | `GET …/dataAPI/privateEndpoints` | 200 | `privateEndpointDNS`, `endpoints[]` (`id`, `serviceName`, `status`) |
| Accept endpoint | `POST …/dataAPI/privateEndpoints/{endpointId}/associate` | 204 | |
| Reject endpoint | `POST …/dataAPI/privateEndpoints/{endpointId}/unassociate` | 204 | |

## Design

### Commands
```
capellactl data-api show   CLUSTER
capellactl data-api update CLUSTER --enable|--disable [--network-peering on|off]
capellactl data-api endpoint-command CLUSTER (--vpc-id ID --subnet-id ID … | --resource-group RG --vnet NAME)
capellactl data-api endpoint list   CLUSTER
capellactl data-api endpoint accept CLUSTER ENDPOINT_ID
capellactl data-api endpoint reject CLUSTER ENDPOINT_ID
```
Example:
```
capellactl data-api update nova-dev-01 --enable
capellactl data-api show nova-dev-01
```

### capella.yaml
```yaml
clusters:
  - name: nova-dev-01
    dataApi:
      enabled: true
      networkPeering: false
```
- `update` and `apply` wait until `state` leaves `enabling`/`disabling`/`configuring` (CAP-007). `show` prints the
  state and `connectionString`.
- Private-endpoint acceptance is imperative: endpoints are created in the customer's cloud account, so they are not
  declared in capella.yaml. `endpoint-command` prints the cloud CLI command to run.
- Code: `cli/data_api_cmds.py`, `resources/data_api.py` (child of the cluster), six operations, fake Capella.

## Acceptance criteria & tests

### AC1 — Enable from the CLI and the file
**Given** `data-api update nova-dev-01 --enable`, **then** one `PUT` with `enableDataApi: true,
enableNetworkPeering: false`, a wait until `enabled`, and capella.yaml records `dataApi`.

| Test | Location | Verifies |
|---|---|---|
| `test_data_api_ac1_enable` | `tests/scenario/test_data_api.py` | |

### AC2 — Idempotent
**Given** AC1 completed, **then** `apply` makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_data_api_ac2_rerun_zero_writes` | `tests/scenario/test_data_api.py` | |

### AC3 — Show
**Given** an enabled Data API, **then** `show` prints `enabled · https://… (connection string) · network peering off`;
`-o json` returns Capella's body.

| Test | Location | Verifies |
|---|---|---|
| `test_data_api_ac3_show` | `tests/scenario/test_data_api.py` | |

### AC4 — Private endpoints
**Given** a pending endpoint, **then** `endpoint list` prints `S.NO`, `SERVICE`, `STATUS`, `ID`; `accept` sends
`associate`; `reject` asks once and sends `unassociate`; `endpoint-command` prints the command for the given cloud
and refuses mixed AWS/Azure flags with exit 3.

| Test | Location | Verifies |
|---|---|---|
| `test_data_api_ac4_endpoints` | `tests/scenario/test_data_api.py` | |

### AC5 — Turned-off or free-tier cluster
**Given** a turned-off cluster, **then** exit 4 (cluster turned off); a free-tier cluster, exit 4 with the API's
reason; zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_data_api_ac5_blocked_states` | `tests/scenario/test_data_api.py` | |

### AC6 — sync and drift
**Given** a Data API enabled in Capella, **then** `sync` writes `dataApi` and `drift` reports a difference.

| Test | Location | Verifies |
|---|---|---|
| `test_data_api_ac6_sync_drift` | `tests/scenario/test_data_api.py` | |

## Out of scope
- Calling the Data API itself (document reads and writes).

## Open questions
- Can the Data API be enabled on a free-tier cluster? AC5 assumes not; confirm in the sandbox.
