# CAP-024 — Delete bucket

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E7 Data model | P0 | 2 | CAP-023, CAP-013 | Implemented |

## User story
As an **operator**, I want to delete a bucket deliberately and safely, so that data is never lost by accident.

## Context & discovery
- `DELETE …/clusters/{clusterId}/buckets/{bucketId}` → `204`.
- Deletion protection on the cluster prevents bucket deletion (CAP-013).
- Bucket `GET` includes `stats` (item count, memory/disk usage) for the confirmation.

## Implementation details
`capellactl bucket delete CLUSTER NAME [--auto-approve]`; also reached through `apply --prune` and `destroy`. Confirmation shows name, item count, memory used and the credentials that reference the bucket, and requires typing the bucket name.

## Acceptance criteria & tests

### AC1 — Delete with typed confirmation
**Given** bucket `orders` with 1,204 items, **then** the prompt shows `orders · 1,204 items · 412 MB used`, typing `orders` sends `DELETE …/buckets/b3JkZXJz` (ID from the list response) and prints `deleted bucket nova-dev-01/orders`.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_delete_ac1_confirm_and_delete` | `tests/scenario/test_bucket_delete.py` | Also: wrong name cancels; non-interactive needs `--auto-approve` |

### AC2 — Protected cluster
**Given** deletion protection on, **then** exit 4, zero writes (CAP-013 message).

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_delete_ac2_protection_blocks` | `tests/scenario/test_bucket_delete.py` | |

### AC3 — Credentials referencing the bucket
**Given** `orders_app` and `reporting_ro` reference `orders`, **then** the confirmation lists them under `These credentials lose access to this bucket:`; the delete is not blocked.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_delete_ac3_lists_dependent_credentials` | `tests/scenario/test_bucket_delete.py` | |

### AC4 — Removing from the file is not deleting
**Given** `orders` is removed from `capella.yaml`, **then** `apply` makes no delete and `drift` lists it as unmanaged; `apply --prune` plans `- bucket nova-dev-01/orders` with the AC1 confirmation.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_delete_ac4_removed_from_file_not_deleted` | `tests/scenario/test_bucket_delete.py` | `apply` part; `drift` part with CAP-031 |
| `test_bucket_delete_ac4_prune_deletes` | same | Also `test_bucket_delete_ac4_prune_respects_protection` |

### AC5 — Idempotent re-run
**Given** AC1 completed, **then** re-running prints `not found, nothing to do`, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_delete_ac5_rerun_noop` | `tests/scenario/test_bucket_delete.py` | |

## Out of scope
- Bucket flush (`PUT …/flush`), deliberately not exposed in 1.0.0.

## Open questions
- None.

## Implementation notes (as built)

- `capellactl bucket delete CLUSTER NAME [--project NAME]` (`cli/bucket_cmds.py`). It shows `- bucket CLUSTER/NAME`, then `NAME · N items · M MB used` from the bucket `GET`'s `stats` (`itemCount`, `memoryUsedInMib`), then the dependent credentials, and asks for the bucket name to be typed (skipped with `--auto-approve`; refused without a terminal). After the `DELETE` (ID from the list response) it also **removes the bucket from `capella.yaml`**, so the next `apply` does not create it again.
- **AC2**: the check reads `deletionProtection` from the cluster as listed, through CAP-013's shared guard (`resources/guards.py`: `deletion_protected`, `protection_message`). The not-found check (AC5) runs first: deleting a bucket that is already gone is a no-op even on a protected cluster.
- **AC3**: a credential is listed when any of its `access[].resources.buckets[].name` is the bucket. Credentials without `resources` (all buckets) are not listed.
- **AC4**: `apply --prune` is introduced here for prunable kinds (buckets only: `Reconciler.prunable` / `delete_action`, planner option `prune`); CAP-031 extends it to the other kinds. A prune on a protected cluster is BLOCKED with the AC2 message. In `apply`, each bucket delete's typed confirmation comes before the usual "Apply N changes?" question. The `drift` half of AC4 (lists it as unmanaged) is delivered by CAP-031, which owns `drift`.
- Bucket `stats` keys checked against the v4.0 OpenAPI spec: `itemCount`, `opsPerSecond`, `diskUsedInMib`, `memoryUsedInMib` (first built with `…InMiB`, which never matched). Free-tier buckets are deleted through `DELETE …/buckets/freeTier/{bucketId}`.
