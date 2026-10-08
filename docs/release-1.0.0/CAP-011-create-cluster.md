# CAP-011 — Create cluster

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E3 Clusters | P0 | 5 | CAP-007, CAP-009 | Implemented |

## User story
As an **operator**, I want `apply` to create a cluster with the cloud, region, sizing, services and support plan I declare, and wait until it is ready, so that every environment is built the same way.

## Context & discovery

| Operation | Endpoint | Success |
|---|---|---|
| List | `GET …/projects/{projectId}/clusters` | 200 |
| Get | `GET …/clusters/{clusterId}` | 200 + `ETag`; includes `currentState`, `deletionProtection`, `connectionString`, `expressScaling` |
| Create | `POST …/projects/{projectId}/clusters` | **202** `{id}` |

Create body (from the spec; `*` = required):

| Field | Notes |
|---|---|
| `name*` | ≤ 256 characters |
| `description` | ≤ 1024 |
| `configurationType` | `multiNode` (default) or `singleNode`; singleNode: any provider (AWS, GCP, Azure), `availability: single`, plan `basic`/`developer pro`, 1 node, services from `data, index, query, search` |
| `cloudProvider*` | `type*` `aws`/`gcp`/`azure`; `region*` (name must match the provider's naming: aws `us-east-1`, gcp `us-east1`, azure `eastus`; checked by shape only, so new regions pass); `cidr` |
| `couchbaseServer.version` | optional |
| `serviceGroups*` | `node.compute{cpu*, ram*}`, `node.disk` (AWS `gp3`/`io2` + `storage*` ≥ 50 + `iops*`; Azure `P6`…`P60`/`Ultra` (+ `storage`, `iops` for Ultra, `autoExpansion`); GCP `pd-ssd` + `storage*` ≥ 50), `numOfNodes`, `services` |
| `availability*` | `type*` `single`/`multi` |
| `support*` | `plan*` `basic`/`developer pro`/`enterprise`; `timezone` `ET`/`GMT`/`IST`/`PT` (ignored for basic) |
| `zones` | single-AZ only, one zone |
| `cmekId`, `enablePrivateDNSResolution` | pass-through |

Roles: Organization Owner, Project Owner, Project Manager.

## Implementation details
- `resources/cluster.py` → `CREATE` sends only API fields (never `allowedCidrs`, `buckets`, `databaseCredentials`, `deletionProtection`, `hibernation`).
- After `202`: `wait_for_cluster(op="create")` (CAP-007). Children are reconciled only after `healthy`.
- Final summary prints `connectionString`.

## Acceptance criteria & tests

### AC1 — Create request body
**Given** the cluster in [examples/capella.yaml](examples/capella.yaml) does not exist, **then** the plan shows `+ cluster nova-dev-01  aws us-east-1 · multi-AZ · 3 × 4 vCPU/16 GB · data,index,query · developer pro`, and the `POST` body equals the fixture `tests/scenario/fixtures/cluster_create_body.json` (no non-API keys).

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_ac1_create_body_matches_fixture` | `tests/scenario/test_cluster_create.py` | |
| `test_cluster_ac1_plan_line_summary` | same | |
| `test_endpoints_ac1_create_cluster_contract` | `tests/contract/test_endpoints_cluster.py` | 202 parsed |

### AC2 — Waits, then creates children
**Given** the create returns `202`, **then** no child write happens until the fake reports `healthy`; the summary includes `connectionString: couchbases://cb.xxxx.cloud.couchbase.com`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_ac2_children_after_healthy` | `tests/scenario/test_cluster_create.py` | Order + fake clock |
| `test_cluster_ac2_summary_connection_string` | same | |

### AC3 — Existing cluster is not re-created
**Given** a cluster with that name exists and matches, **then** `= cluster nova-dev-01`, zero writes. **Given** it is `deploying`, **then** apply waits and sends no `POST`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_ac3_existing_matches_noop` | `tests/scenario/test_cluster_create.py` | |
| `test_cluster_ac3_deploying_waits_no_post` | same | |

### AC4 — Failed deployment is never auto-deleted
**Given** a cluster with that name in `deploymentFailed`, **then** `! cluster nova-dev-01  in deploymentFailed; delete it (capellactl cluster delete nova-dev-01) and re-run apply`, exit 4, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_ac4_deployment_failed_blocked` | `tests/scenario/test_cluster_create.py` | |

### AC5 — Offline validation of create rules
**Given** each invalid config below, **then** `validate` exits 3 with a specific message: no `data` service; `singleNode` with `availability: multi`; `singleNode` with `numOfNodes: 3`; AWS disk `pd-ssd`; AWS `storage: 20`; `zones` with two entries; `zones` with `availability: multi`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_validate_ac5_rules` | `tests/unit/config/test_cluster_rules.py` | Parametrised |

### AC6 — API validation errors surfaced
**Given** the API returns `422` (for example unsupported compute in region), **then** the CLI prints the API `message` and `hint`, exit 1, and nothing else is attempted. **Given** a `5xx` on a create or update, **then** Capella's generic hint is replaced by one saying the cause is often an unsupported value (region, size, disk) rather than an outage. **Given** a region named for another provider (for example azure `us-east-1`), **then** `validate` exits 3 before any request (Capella answers it with a bare `500`).

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_ac6_422_message_and_hint` | `tests/scenario/test_cluster_create.py` | |

### AC7 — Idempotent re-run
**Given** AC1–AC2 completed, **when** `apply` runs again, **then** zero writes, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_ac7_rerun_zero_writes` | `tests/scenario/test_cluster_create.py` | |
| `test_cluster_create_ac7_integration` | `tests/integration/test_cluster_lifecycle.py` | Real sandbox, singleNode |

## Out of scope
- Free-tier clusters (`/clusters/freeTier`).
- Creating CMEK keys (an existing `cmekId` is passed through).

## Open questions
- Supported compute/disk combinations per region are documented outside the spec. Should `validate` ship a static table, or rely on the API `422`? (Proposed: rely on the API in 1.0.0.)

## Implementation notes (as built)
- AC2 summary line format is `connectionString (<cluster>): couchbases://…` so several clusters can be listed.
- AC7's real-Capella check (`test_cluster_create_ac7_integration`) is part of the nightly suite (CAP-032), not yet written.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_cluster_ac1_create_body_matches_fixture` (tests/scenario/test_cluster_create.py)<br>`test_cluster_ac1_plan_line_summary` (tests/scenario/test_cluster_create.py) |
| AC2 | `test_cluster_ac2_children_after_healthy` (tests/scenario/test_cluster_create.py)<br>`test_cluster_ac2_summary_connection_string` (tests/scenario/test_cluster_create.py) |
| AC3 | `test_cluster_ac3_existing_matches_noop` (tests/scenario/test_cluster_create.py)<br>`test_cluster_ac3_deploying_waits_no_post` (tests/scenario/test_cluster_create.py) |
| AC4 | `test_cluster_ac4_deployment_failed_blocked` (tests/scenario/test_cluster_create.py) |
| AC5 | `test_cluster_validate_ac5_rules` (tests/scenario/test_cluster_create.py) |
| AC6 | `test_cluster_ac6_422_message_and_hint` (tests/scenario/test_cluster_create.py) |
| AC7 | `test_cluster_ac7_rerun_zero_writes` (tests/scenario/test_cluster_create.py) |
