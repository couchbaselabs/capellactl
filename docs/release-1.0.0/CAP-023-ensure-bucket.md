# CAP-023 — Ensure bucket (create & update)

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E7 Data model | P0 | 5 | CAP-011 | Implemented |

## User story
As an **application team lead**, I want buckets created with the agreed memory, replica, durability, TTL and storage settings, and corrected when they drift, so that every environment has the same data configuration.

## Context & discovery

| Operation | Endpoint | Success |
|---|---|---|
| List / get | `GET …/clusters/{clusterId}/buckets[/{bucketId}]` | 200 |
| Create | `POST …/clusters/{clusterId}/buckets` | 201 `{id}` |
| Update | `PUT …/buckets/{bucketId}` | 204 |
| Capacity | `GET …/clusters/{clusterId}/stats` | 200 `{totalMemoryInMb, freeMemoryInMb, maxReplicas}` |

- Bucket `id` is the base64 encoding of the name (example `dGVzdA` for `test`) — always read from the list response.
- Create fields: `name*`, `type` (`couchbase`/`ephemeral`), `storageBackend` (`couchstore`/`magma`; not for ephemeral), `vbuckets` (128/1024; magma, server ≥ 8.0), `memoryAllocationInMb`, `bucketConflictResolution` (`seqno`/`lww`), `durabilityLevel` (`none`, `majority`, `majorityAndPersistActive`, `persistToMajority`), `replicas` (1–3), `flushEnabled` (replaces deprecated `flush`), `timeToLiveInSeconds`, `evictionPolicy` (`fullEviction`, `noEviction`, `nruEviction`), `priority`.
- Update requires `memoryAllocationInMb*`, `durabilityLevel*`, `replicas*`, `timeToLiveInSeconds*`; optional `flushEnabled`, `enableCrossClusterVersioning`, `priority`.

## Implementation details
- Immutable (→ BLOCKED): `type`, `storageBackend`, `vbuckets`, `bucketConflictResolution`, `evictionPolicy`.
- Update body = observed overlaid with desired ([00-architecture.md §6.4](00-architecture.md#64-full-replacement-updates)).
- Pre-flight capacity check before creates and memory increases: sum of new/increased allocations ≤ `freeMemoryInMb`; replicas ≤ `maxReplicas`.

## Acceptance criteria & tests

### AC1 — Create
**Given** bucket `orders` is missing, **then** `+ bucket nova-dev-01/orders  couchbase · magma · 1024 MB · 1 replica · durability majority` and one `POST` with the configured fields; `flushEnabled` is sent, `flush` never.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_ac1_create_body` | `tests/scenario/test_bucket.py` | Plan line, one `POST`, `flushEnabled` sent and `flush` never |
| `test_endpoints_ac1_bucket_contract` | `tests/contract/test_endpoints_bucket.py` | Method, path and body of create/update/stats/delete |

### AC2 — No-op with defaults
**Given** Capella matches after defaults are applied, **then** `=`, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_ac2_defaults_noop` | `tests/scenario/test_bucket.py` | Defaults applied; deprecated `flush` read when `flushEnabled` is absent |

### AC3 — Update updatable fields with full body
**Given** `memoryAllocationInMb` 1024 → 2048 only, **then** `~ memoryAllocationInMb: 1024 → 2048` and one `PUT` whose body includes observed `durabilityLevel`, `replicas`, `timeToLiveInSeconds` plus the new memory.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_ac3_update_full_body` | `tests/scenario/test_bucket.py` | Only the memory change shown; `PUT` keeps observed fields |
| `test_bucket_body_ac3_overlay` | `tests/unit/resources/test_bucket_body.py` | |

### AC4 — Immutable fields blocked
**Given** a change to `type`, `storageBackend`, `vbuckets`, `bucketConflictResolution` or `evictionPolicy`, **then** `! bucket … storageBackend: couchstore → magma  BLOCKED (immutable; create a new bucket and migrate data)`, exit 4.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_ac4_immutable_blocked` | `tests/scenario/test_bucket.py` | Parametrised |

### AC5 — Offline type rules
**Given** an ephemeral bucket with `storageBackend`, or `evictionPolicy: fullEviction` on ephemeral, or `nruEviction` on couchbase, or `durabilityLevel: persistToMajority` on ephemeral, **then** `validate` exits 3 with the rule.

On a free-tier cluster, `bucket create`/`update` with a flag other than `--memory` (and `--cross-cluster-versioning` on update) exits 3 before anything is written, naming the cluster, its project and the refused flags; interactive `update` asks only for memory.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_validate_ac5_type_rules` | `tests/unit/config/test_bucket_rules.py` | Parametrised; plus `validate` exit 3 |
| `test_bucket_free_ac5_other_settings_refused` | `tests/scenario/test_bucket_free_tier.py` | flags named, no YAML path |
| `test_bucket_free_ac5_interactive_update_asks_memory_only` | `tests/scenario/test_bucket_free_tier.py` | |

### AC6 — Capacity pre-flight
**Given** `freeMemoryInMb: 512` and a new bucket of 1024 MB, **then** `! bucket … needs 1024 MB but the cluster has 512 MB free; scale out (CAP-015) or reduce memoryAllocationInMb`, exit 4. **Given** `replicas: 3` and `maxReplicas: 2`, **then** blocked similarly.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_ac6_memory_preflight_blocks` | `tests/scenario/test_bucket.py` | Also: several new buckets summed, memory increases |
| `test_bucket_ac6_replica_preflight_blocks` | same | |

### AC7 — Replica change note
**Given** `replicas` 1 → 2, **then** the plan adds `note: the new replica count takes full effect after a rebalance`.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_ac7_replica_change_note` | `tests/scenario/test_bucket.py` | |

### AC8 — Idempotent re-run
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_ac8_rerun_zero_writes` | `tests/scenario/test_bucket.py` | Including `enableCrossClusterVersioning` (update-only field) |
| `test_bucket_ac8_integration` | `tests/integration/test_data_model.py` | Nightly, sandbox |

## Out of scope
- Bucket flush; sample buckets; backup schedules.

## Open questions
- ~~Minimum `memoryAllocationInMb` per storage backend~~ — 1.0.0 relies on the API's `422` (shown with Capella's hint); encoding the minimums in `validate` moves to 1.1.

## Implementation notes (as built)
- Single-node replicas (2026-10-07): Capella answers 422 `Single-node clusters only support a replica count of '0'` although the API spec lists 1-3. Buckets on `configurationType: singleNode` clusters now default to `replicas: 0`; any other value there, and `replicas: 0` on multi-node clusters, fail validation (exit 3). `--replicas` accepts 0. The old 'replica is placed when data nodes are added' note was based on the wrong assumption. Test: `test_bucket_ac6_single_node_uses_zero_replicas` (tests/scenario/test_bucket_free_tier.py).
- Interrupted create (2026-10-07): `bucket create` for a bucket that is in capella.yaml but not in Capella (an earlier run saved it and then failed) now updates that entry with the given flags and creates it. Before, `create` refused (`already in capella.yaml`) and `update` could not set `--storage-backend`/`--type`, so there was no way out except `apply`. A bucket that exists in Capella is still refused. Test: `test_bucket_cli_ac1_create_finishes_recorded_bucket` (tests/scenario/test_bucket.py).
- Free-tier flags (2026-10-07): `bucket create`/`update` check the flags against the cluster's `tier: free` before editing capella.yaml. Before, the refusal came from validating the unsaved candidate file, so it showed a YAML path (`projects[1].clusters[0].buckets[0].storageBackend`) and a line number that did not match the file on disk.

- `capellactl/resources/bucket.py` (`BucketReconciler`) replaces the deferred bucket placeholder; each bucket has a deferred `scope` child until CAP-025. The test stub tree also uses the real reconciler now.
- **Commands.** Buckets are managed with `bucket list | get | create | update | delete` (00-architecture.md §5 "Verbs"), not a per-resource `apply`. `bucket create` / `bucket update` change `capella.yaml`, validate it, show this bucket's plan, ask once and apply (`--no-apply` only records it); `create` for a bucket that already exists in Capella adopts it. `update` offers only updatable fields. `apply` still reconciles every bucket in the file.
- **Capacity pre-flight** reads `GET …/stats` once per cluster and plan and subtracts each planned create and memory increase from `freeMemoryInMb`, so several new buckets are checked together. It is skipped while the cluster does not exist yet (the bucket is created after the cluster is healthy). A bucket without `memoryAllocationInMb` is only checked for replicas.
- **AC6 replicas** — the API's `replicas` enum starts at 1, so on a cluster with one data node (`maxReplicas: 0`, for example free tier or `singleNode`) 1 replica is accepted with `note: the cluster has one data node; the replica is placed when data nodes are added`; only more than `max(maxReplicas, 1)` is blocked. (First built as `replicas > maxReplicas`, which made buckets impossible on one-node clusters.)
- **Free-tier clusters** use the Free Tier bucket endpoints from the v4.0 spec: `GET|POST …/clusters/{clusterId}/buckets/freeTier` and `GET|PUT|DELETE …/buckets/freeTier/{bucketId}`. Create takes only `name` and `memoryAllocationInMb` (default 100); update takes `memoryAllocationInMb` and `enableCrossClusterVersioning`. The list is not paginated and carries `clusterStats`, used for the memory pre-flight. On free-tier clusters no bucket defaults are applied, only those two fields are compared, the plan shows `free tier · 100 MB`, and `validate` rejects any other bucket field. `import`/`sync` now write free-tier buckets as `name` + `memoryAllocationInMb`. Tests: `tests/scenario/test_bucket_free_tier.py`, `test_endpoints_ac1_free_tier_bucket_contract`.
- **AC4** reason reads `storageBackend: couchstore → magma  BLOCKED (immutable; create a new bucket and migrate data)`; several immutable changes are joined with `;`.
- **AC5** also rejects `majorityAndPersistActive` on ephemeral buckets (they only allow `none`/`majority`), `noEviction` on couchbase buckets, and `vbuckets` without `storageBackend: magma` (`config/crossref.py::bucket_type_rules`).
- **AC7** the note is shown on the bucket's plan line.
- `enableCrossClusterVersioning` is accepted only by the update endpoint, so a new bucket that sets it is created and then updated once; a missing value is compared as `false`.
- Additional tests: `test_bucket_cli_ac1_create_records_and_applies`, `test_bucket_cli_ac1_create_already_in_file_refused`, `test_bucket_cli_ac3_update_records_and_applies`, `test_bucket_cli_ac3_update_not_in_file`, `test_bucket_ac6_memory_preflight_sums_new_buckets`, `test_bucket_ac6_memory_increase_preflight`, `test_bucket_list_and_get`.
