# CAP-065 — Sample buckets

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E11 Data access & tools | P2 | 2 | CAP-023, CAP-024 | Not started |

## User story
As a **developer**, I want to load one of Couchbase's sample datasets into a cluster with one command, so that I
can try queries, indexes and SDK code on realistic data straight after `cluster create`.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Load sample | `POST …/clusters/{clusterId}/sampleBuckets` | 201 | `name`: `travel-sample`, `gamesim-sample`, `beer-sample`, `inventory-sample` → `bucketId`, `name` |
| List samples | `GET …/clusters/{clusterId}/sampleBuckets` | 200 | Bucket fields + `clusterStats` (`freeMemoryInMb`, `totalMemoryInMb`) |
| Get sample | `GET …/clusters/{clusterId}/sampleBuckets/{bucketId}` | 200 | Same fields as a bucket, with `stats` |
| Delete sample | `DELETE …/clusters/{clusterId}/sampleBuckets/{bucketId}` | 204 | |

A sample bucket is an ordinary bucket once loaded, so `bucket list` also shows it.

## Design
```
capellactl sample-bucket list   CLUSTER
capellactl sample-bucket load   CLUSTER travel-sample|gamesim-sample|beer-sample|inventory-sample
capellactl sample-bucket get    CLUSTER NAME
capellactl sample-bucket delete CLUSTER NAME
```
Examples:
```
capellactl sample-bucket load nova-dev-01 travel-sample
capellactl sample-bucket list nova-dev-01
```
- Imperative only: samples are not declared in capella.yaml. `sync` skips buckets whose name is a sample name and
  `drift` does not report them as unmanaged (one rule in `resources/bucket.py`).
- `load` checks `clusterStats.freeMemoryInMb` first and refuses (exit 4) when the cluster has too little free memory,
  with the CAP-017 hint to raise RAM.
- Code: `cli/sample_bucket_cmds.py` (new), four operations in `api/endpoints.py`, fake Capella extended.

## Acceptance criteria & tests

### AC1 — Load
**Given** `sample-bucket load nova-dev-01 travel-sample`, **then** one `POST` with `{"name": "travel-sample"}` is
sent and `loaded sample bucket nova-dev-01/travel-sample` is printed. An unknown name exits 3 with the four valid
names.

| Test | Location | Verifies |
|---|---|---|
| `test_sample_bucket_ac1_load` | `tests/scenario/test_sample_buckets.py` | Also the unknown-name error |

### AC2 — Idempotent
**Given** `travel-sample` is already loaded, **then** `load` prints `already loaded`, exit 0, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_sample_bucket_ac2_rerun_zero_writes` | `tests/scenario/test_sample_buckets.py` | |

### AC3 — Not enough memory
**Given** `freeMemoryInMb` below the sample's quota, **then** exit 4 with the free memory and a `cluster update
--ram` hint, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_sample_bucket_ac3_low_memory_blocked` | `tests/scenario/test_sample_buckets.py` | |

### AC4 — List, get, delete
**Given** loaded samples, **then** `list` prints `S.NO`, `NAME`, `ITEMS`, `MEMORY`, `ID`; `get` shows the stats;
`delete` asks for the name to be typed (as CAP-024) and respects deletion protection (exit 4).

| Test | Location | Verifies |
|---|---|---|
| `test_sample_bucket_ac4_list_get` | `tests/scenario/test_sample_buckets.py` | |
| `test_sample_bucket_ac4_delete` | same | Also protection |

### AC5 — Not drift
**Given** a loaded sample and a capella.yaml without it, **then** `plan`, `drift` and `sync` ignore it.

| Test | Location | Verifies |
|---|---|---|
| `test_sample_bucket_ac5_ignored_by_environment` | `tests/scenario/test_sample_buckets.py` | |

## Out of scope
- Declaring samples in capella.yaml.

## Open questions
- Is the memory a sample needs documented per sample? If not, use 200 MB, the documented minimum bucket quota.
