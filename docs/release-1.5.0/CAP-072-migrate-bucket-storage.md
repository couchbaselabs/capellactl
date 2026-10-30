# CAP-072 — Migrate bucket storage backend

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E12 Replication & cluster operations | P2 | 3 | CAP-023, CAP-012 | Not started |

## User story
As an **operator**, I want to move buckets from Couchstore to Magma (or back) with one command, so that I can adopt
the storage engine that suits my data size without recreating the buckets.

## Context & discovery
- `PUT …/clusters/{clusterId}/bucketStorageMigration` → 202. Body: `buckets` (array of bucket IDs). The bucket's
  `storageBackend` is immutable through `PUT …/buckets/{bucketId}` (CAP-023 blocks it), so this is the only way to
  change it.
- The migration rewrites data in the background; the bucket stays online.

## Design
```
capellactl cluster migrate-buckets CLUSTER BUCKET … --to magma|couchstore
```
Example:
```
capellactl cluster migrate-buckets nova-dev-01 orders --to magma
```
- Before sending, reads each bucket and checks the target backend is different and permitted (Magma needs the
  memory and vbucket minimums documented for Magma; checked against the cluster's buckets), then asks once.
- After the 202, waits until each bucket's `storageBackend` reads the target (CAP-007; `--no-wait` returns at once)
  and updates `storageBackend` in capella.yaml.
- With CAP-023, a `storageBackend` change in capella.yaml stays BLOCKED in `plan`, but the message now points to
  `cluster migrate-buckets`.
- Code: `cli/cluster_ops.py` gains `migrate-buckets`; one operation; the fake flips the backend after a delay.

## Acceptance criteria & tests

### AC1 — Migrate
**Given** bucket `orders` on Couchstore, **then** one `PUT` with `buckets: [<orders id>]`, a wait until it reads
`magma`, and capella.yaml updated.

| Test | Location | Verifies |
|---|---|---|
| `test_migrate_buckets_ac1_migrate` | `tests/scenario/test_migrate_buckets.py` | |

### AC2 — Nothing to do
**Given** the bucket is already on the target, **then** `already magma`, exit 0, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_migrate_buckets_ac2_noop` | `tests/scenario/test_migrate_buckets.py` | |

### AC3 — Refused
**Given** an unknown bucket, a free-tier cluster, or a bucket below the target backend's minimums, **then** exit 3 or
4 with the reason, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_migrate_buckets_ac3_refused` | `tests/scenario/test_migrate_buckets.py` | Parametrised |

### AC4 — plan points to the command
**Given** `storageBackend` changed in capella.yaml, **then** `plan` shows BLOCKED with `use: capellactl cluster
migrate-buckets nova-dev-01 orders --to magma`.

| Test | Location | Verifies |
|---|---|---|
| `test_migrate_buckets_ac4_plan_hint` | `tests/scenario/test_migrate_buckets.py` | |

## Out of scope
- Migrating every bucket of a cluster with one flag.

## Open questions
- Is there a way to read migration progress other than polling the bucket's `storageBackend`?
