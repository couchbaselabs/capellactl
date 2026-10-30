# CAP-067 — Query indexes as code

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E11 Data access & tools | P0 | 5 | CAP-025 | Not started |

## User story
As an **operator**, I want to declare a collection's secondary indexes in capella.yaml and have `apply` create, drop
and build them, so that every environment has the same indexes and a new cluster is query-ready after one apply.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Manage indexes | `POST …/clusters/{clusterId}/queryService/indexes` | 200 | `definition`: one `CREATE INDEX`, `DROP INDEX` or `BUILD INDEX` statement; `errors[].msg` on failure |
| List definitions | `GET …/clusters/{clusterId}/queryService/indexes` | 200 | `bucket`, `scope`, `collection` query params → `definitions[]` (`indexName`, `definition`) |
| Get index | `GET …/clusters/{clusterId}/queryService/indexes/{indexName}` | 200 | `isPrimary`, `secExprs`, `where`, `numReplica`, `status` |
| Build status | `GET …/clusters/{clusterId}/queryService/indexBuildStatus/{indexName}` | 200 | `status`: `Created`, `Ready`, `Building` |

The cluster needs the index and query services (CAP-051 service groups).

## Design

### Commands
```
capellactl index list   CLUSTER --bucket B [--scope S] [--collection C]
capellactl index get    CLUSTER NAME --bucket B [--scope S] [--collection C]
capellactl index status CLUSTER NAME --bucket B [--scope S] [--collection C]
capellactl index create CLUSTER NAME --bucket B [--scope S] [--collection C] --on EXPR … [--where EXPR] [--replicas N] [--defer]
capellactl index drop   CLUSTER NAME --bucket B [--scope S] [--collection C]
capellactl index build  CLUSTER --bucket B [--scope S] [--collection C] [NAME …]
```
`create`, `drop` and `build` all send one statement to `POST …/queryService/indexes`. Example:
```
capellactl index create nova-dev-01 idx_status --bucket orders --scope sales --collection orders --on status
```

### capella.yaml
```yaml
buckets:
  - name: orders
    scopes:
      - name: sales
        collections:
          - name: orders
            indexes:
              - name: idx_status
                keys: [status]
                where: "type = 'order'"   # optional
                replicas: 0              # optional, default 0
```
- Indexes reconcile after their collection. A changed `keys` or `where` is a **replace** (`±`: drop then create),
  since an index cannot be altered; `replicas` changes are also replaced.
- `apply` creates indexes deferred and sends one `BUILD INDEX` per collection, then waits on the build status until
  `Ready` (the CAP-007 waiter; `--no-wait` returns at `Building`).
- Comparison uses `GET …/indexes/{name}` (`secExprs`, `where`, `numReplica`), normalising back-quotes and spacing.
- Code: `cli/index_cmds.py`, `resources/query_index.py` (prunable), four operations in `api/endpoints.py`, fake
  Capella that parses the three statement kinds it accepts.

## Acceptance criteria & tests

### AC1 — Create and build from capella.yaml
**Given** two declared indexes on `orders.sales.orders`, **then** `apply` sends two deferred `CREATE INDEX`
statements, one `BUILD INDEX`, waits until both are `Ready`, and `plan` then reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_index_ac1_apply_creates_and_builds` | `tests/scenario/test_query_indexes.py` | Statements, wait, no drift |

### AC2 — Idempotent
**Given** AC1 completed, **then** a re-run makes zero `POST`/`PUT`/`DELETE` calls.

| Test | Location | Verifies |
|---|---|---|
| `test_index_ac2_rerun_zero_writes` | `tests/scenario/test_query_indexes.py` | |

### AC3 — Changed definition is replaced
**Given** `keys` changed, **then** `plan` shows `± index orders.sales.orders/idx_status` with `keys before → after`,
and `apply` drops then creates and builds it.

| Test | Location | Verifies |
|---|---|---|
| `test_index_ac3_change_is_replace` | `tests/scenario/test_query_indexes.py` | |

### AC4 — Capella errors are shown
**Given** the API returns `errors[].msg` for a statement, **then** exit 1 with the message and the statement sent.
**Given** a cluster without the index service, **then** exit 4 before any write.

| Test | Location | Verifies |
|---|---|---|
| `test_index_ac4_statement_error` | `tests/scenario/test_query_indexes.py` | |
| `test_index_ac4_no_index_service_blocked` | same | |

### AC5 — Commands
**Given** the commands above, **then** `list` prints `S.NO`, `NAME`, `KEYS`, `STATUS`, `ID` (`defnId`); `create`
records the index in capella.yaml and applies it; `drop` asks once and removes it from the file; `status` prints
`Created`, `Building` or `Ready`.

| Test | Location | Verifies |
|---|---|---|
| `test_index_ac5_commands` | `tests/scenario/test_query_indexes.py` | |

### AC6 — sync, drift, prune
**Given** indexes in Capella, **then** `sync` writes them under their collection (primary indexes as `primary: true`),
`drift` lists unmanaged ones, `apply --prune` drops them.

| Test | Location | Verifies |
|---|---|---|
| `test_index_ac6_sync_drift_prune` | `tests/scenario/test_query_indexes.py` | |

## Out of scope
- Search (FTS), analytics and vector indexes; the API has no operations for them.
- Index partitioning (`PARTITION BY`).

## Open questions
- Can one `definition` carry several statements? The spec describes a single statement; build one at a time unless
  confirmed.
