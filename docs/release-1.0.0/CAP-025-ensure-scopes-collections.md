# CAP-025 — Ensure scopes & collections

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E7 Data model | P0 | 5 | CAP-023 | Implemented |

## User story
As an **application team lead**, I want scopes and collections declared under each bucket, so that the application's data model exists before the application is deployed.

## Context & discovery

| Operation | Endpoint | Success |
|---|---|---|
| List / get scope | `GET …/buckets/{bucketId}/scopes[/{scopeName}]` | 200 |
| Create scope | `POST …/buckets/{bucketId}/scopes` | 201; body `name*` (1–251 chars, `A-Z a-z 0-9 _ - %`) |
| List / get collection | `GET …/scopes/{scopeName}/collections[/{collectionName}]` | 200 |
| Create collection | `POST …/scopes/{scopeName}/collections` | 201; body `name*`, `maxTTL` |
| Update collection | `PUT …/collections/{collectionName}` | 204; body `maxTTL*`; **server ≥ 7.6.0 only**; `412` on stale ETag |

`maxTTL`: `-1` never expire, `0` use the bucket's TTL, `> 0` seconds.

## Implementation details
```yaml
buckets:
  - name: orders
    scopes:
      - name: inventory
        collections:
          - name: items
          - name: suppliers
            maxTTL: -1
      - name: billing
        collections:
          - name: invoices
```
- `_default`/`_system` scopes and the `_default` collection are system objects: never created, changed or deleted; `_default` may be declared so its collections can be managed.
- Server version comes from the cluster `GET` (`couchbaseServer.version`).

## Acceptance criteria & tests

### AC1 — Create scopes and collections
**Given** none exist, **then** `+ scope nova-dev-01/orders/inventory`, `+ collection nova-dev-01/orders/inventory/items` etc., with scope `POST` before its collection `POST`s; `maxTTL` omitted when not set.

| Test | Location | Verifies |
|---|---|---|
| `test_scopes_ac1_create_order_and_bodies` | `tests/scenario/test_scopes_collections.py` | Plan lines; POST order and bodies; `maxTTL` omitted when unset. Also `test_scopes_ac1_new_bucket_children_after_bucket` |
| `test_endpoints_ac1_scope_collection_contract` | `tests/contract/test_endpoints_scope.py` | Method, path, body and `If-Match` of all nine scope/collection operations |

### AC2 — Collection maxTTL update
**Given** `suppliers` has `maxTTL: 0` and the file says `-1` on server 7.6.2, **then** `~ collection … maxTTL: 0 → -1` and `PUT …/collections/suppliers {"maxTTL": -1}` with `If-Match`.

| Test | Location | Verifies |
|---|---|---|
| `test_collections_ac2_maxttl_update` | `tests/scenario/test_scopes_collections.py` | Plan change line; one `PUT {"maxTTL": -1}` with `If-Match`. Also `test_collections_ac2_stale_etag_replans` (412) |

### AC3 — maxTTL update blocked on old servers
**Given** server 7.2.4, **then** `! collection … maxTTL can only be changed on Couchbase Server 7.6.0 or later`, exit 4.

| Test | Location | Verifies |
|---|---|---|
| `test_collections_ac3_old_server_blocked` | `tests/scenario/test_scopes_collections.py` | Exit 4, zero writes. Also `test_collections_ac3_old_server_still_creates`, `test_collections_ac3_version_gate` |

### AC4 — maxTTL compared only when declared
**Given** the file omits `maxTTL` and Capella has `3600`, **then** `=`.

| Test | Location | Verifies |
|---|---|---|
| `test_collections_ac4_omitted_maxttl_noop` | `tests/unit/resources/test_collection.py` | Also `test_collections_ac4_declared_maxttl_compared` |

### AC5 — System objects untouched
**Given** `_default` is declared with a collection `legacy`, **then** only `+ collection …/_default/legacy` is planned; `_default` itself is never created; `_system` is never listed as unmanaged.

| Test | Location | Verifies |
|---|---|---|
| `test_scopes_ac5_default_scope_collections_only` | `tests/scenario/test_scopes_collections.py` | Existing bucket; also `test_scopes_ac5_default_scope_on_new_bucket` |
| `test_scopes_ac5_system_scope_ignored` | same | Not listed as unmanaged; `apply --prune` leaves them alone |

### AC6 — Name validation
**Given** a scope named `_mine` or `my scope`, or a 252-character name, **then** `validate` exits 3 with the naming rule.

| Test | Location | Verifies |
|---|---|---|
| `test_scope_validate_ac6_names` | `tests/unit/config/test_scope_rules.py` | Parametrised; plus `validate` exit 3 (`test_scope_validate_ac6_validate_exits_3`) |

### AC7 — Created before credentials
**Given** a credential referencing `orders/inventory/items`, **then** all scope and collection writes for `orders` precede the credential `POST`.

| Test | Location | Verifies |
|---|---|---|
| `test_scopes_ac7_before_credentials` | `tests/scenario/test_scopes_collections.py` | Write order: scopes, collections, then users |

### AC8 — Idempotent re-run
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_scopes_ac8_rerun_zero_writes` | `tests/scenario/test_scopes_collections.py` | `plan --detailed-exitcode` 0, no unmanaged items, zero writes |
| `test_scopes_ac8_integration` | `tests/integration/test_data_model.py` | Nightly, sandbox (CAP-032) |

## Out of scope
- Indexes (Query Indexes API) — candidate for 1.1.

## Open questions
- Is a newly created collection immediately usable for credentials, or is there propagation delay? (Credential creation would need a short retry.) — **Deferred to the nightly integration run (CAP-032).** No retry is added in 1.0.0; if the sandbox shows a delay, the credential `POST` gets a short retry on its `422`.

## Implementation notes (as built)

- `capellactl/resources/scope.py` (`ScopeReconciler`, `CollectionReconciler`) replaces the deferred scope placeholder under each bucket (bucket → scopes → collections). The test stub tree uses the real reconcilers too; the old test-only stubs are gone. Endpoints were already in `api/endpoints.py`; `tests/fakes/capella.py` gained `seed_scope`.
- **Commands** (`cli/scope_cmds.py`): `scope list | create | delete` and `collection list | create | update | delete`. `create`/`update` record the change in `capella.yaml`, validate it, show this resource's plan, ask once and apply (`--no-apply` only records it), like the bucket commands. The bucket must already be in the file (else exit 3 pointing to `bucket create`). `scope create` for a scope already in the file just applies it (`already exists in Capella` when there is nothing to do). `collection create` adds its scope to the file when it is new, and is refused (exit 4) when the collection is already there: use `collection update --max-ttl`. `list` marks each item `yes` (in the file), `system` or `-`.
- **AC1**: plan line `+ collection …  maxTTL -1` when `maxTTL` is set. Children of a new bucket are planned with `(after bucket is created)`, collections of a new scope with `(after scope is created)`.
- **AC2**: the update `GET`s the collection for its ETag and sends it as `If-Match`; a `412` re-observes and retries once (executor, CAP-006).
- **AC3**: the server version is the cluster's `couchbaseServer.version` as observed; an unknown version (a cluster still being created) is not blocked. Only *changing* `maxTTL` needs 7.6.0: creating a collection with `maxTTL` is allowed on older servers. Reason: `maxTTL can only be changed on Couchbase Server 7.6.0 or later (nova-dev-01 runs 7.2.4)`, topic `idempotency`.
- **AC5**: a declared `_default` scope is always `=` (never `POST`ed, also on a new bucket). New `Reconciler.manages()` keeps `_default`/`_system` out of the unmanaged list and out of `apply --prune`; the `_default._default` collection and everything in `_system` are filtered out when collections are observed.
- **Unmanaged**: scopes and collections set `reports_unmanaged`, so `plan` lists those in Capella but not in the file (including the scopes of a bucket declared without `scopes:`), and `apply --prune` deletes them (CAP-026).
- **AC6**: `config/crossref.py::keyspace_name_issue`: `scope name '_mine' is not valid: use 1–251 characters of A-Z a-z 0-9 _ - %, not starting with _ or % (_default is the only exception)`. A 252-character name is reported by the schema's `maxLength` (`must be at most 251 characters`).
- **AC7** follows from the tree order: credentials are the last cluster child, after every bucket's scopes and collections.
- **Free-tier buckets** use the same `…/buckets/{bucketId}/scopes` endpoints (the v4.0 spec has no free-tier variant). Not yet verified against a live free-tier cluster.
- Additional tests: `test_scope_cli_ac1_create_records_and_applies`, `test_scope_cli_ac1_bucket_not_in_file`, `test_scope_cli_ac5_system_scope_not_created`, `test_collection_cli_ac1_create_adds_scope`, `test_collection_cli_ac2_update_max_ttl`, `test_collections_ac1_create_summary`, `test_scopes_ac5_system_objects`, `test_scope_validate_ac6_valid_names`, `test_scope_validate_ac6_default_scope_only`.
