# CAP-026 — Delete scopes & collections

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E7 Data model | P0 | 2 | CAP-025 | Implemented |

## User story
As an **operator**, I want to delete a scope or collection deliberately, so that obsolete data models can be removed without touching the rest of the bucket.

## Context & discovery
- `DELETE …/buckets/{bucketId}/scopes/{scopeName}` → 204 (deletes its collections and their documents).
- `DELETE …/scopes/{scopeName}/collections/{collectionName}` → 204.

## Implementation details
```
capellactl scope delete CLUSTER BUCKET SCOPE
capellactl collection delete CLUSTER BUCKET SCOPE COLLECTION
```
Also reached through `apply --prune` and `destroy`.

## Acceptance criteria & tests

### AC1 — Delete a collection
**Given** `orders/billing/invoices` exists, **then** confirmation then `DELETE …/scopes/billing/collections/invoices`.

| Test | Location | Verifies |
|---|---|---|
| `test_collection_delete_ac1_delete` | `tests/scenario/test_scope_collection_delete.py` | Typed confirmation, one `DELETE`, removed from `capella.yaml`. Also `test_collection_delete_ac1_wrong_name_cancels` |

### AC2 — Delete a scope lists its collections
**Given** scope `billing` with collections `invoices`, `refunds`, **then** the confirmation lists both and states that their documents are deleted; one `DELETE …/scopes/billing`.

| Test | Location | Verifies |
|---|---|---|
| `test_scope_delete_ac2_lists_collections` | `tests/scenario/test_scope_collection_delete.py` | Also `test_scope_delete_ac2_protection_blocks` |

### AC3 — System objects refused
**Given** `scope delete … _default` or `_system`, or `collection delete … _default _default`, **then** exit 4 `system scopes and collections cannot be deleted`.

| Test | Location | Verifies |
|---|---|---|
| `test_scope_delete_ac3_system_refused` | `tests/scenario/test_scope_collection_delete.py` | Parametrised; refused before any API call |

### AC4 — Prune only when asked
**Given** a collection removed from the file, **then** `apply` does not delete it; `apply --prune` does, after confirmation.

| Test | Location | Verifies |
|---|---|---|
| `test_collection_delete_ac4_prune_only` | `tests/scenario/test_scope_collection_delete.py` | Also `test_scope_delete_ac4_prune_scope`, `test_collection_delete_ac4_prune_respects_protection` |

### AC5 — Credential references warned
**Given** a credential's access references the scope/collection, **then** the confirmation lists it.

| Test | Location | Verifies |
|---|---|---|
| `test_scope_delete_ac5_lists_dependent_credentials` | `tests/scenario/test_scope_collection_delete.py` | Scope and collection; also `test_collection_delete_ac5_prune_lists_dependent_credentials` |

### AC6 — Idempotent re-run
**Given** AC1 completed, **then** a re-run prints `not found, nothing to do`, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_collection_delete_ac6_rerun_noop` | `tests/scenario/test_scope_collection_delete.py` | Collection and scope |

## Out of scope
- None.

## Open questions
- ~~Is scope/collection deletion blocked by cluster deletion protection?~~ — **Yes, by the tool**: `scope delete`, `collection delete` and `apply --prune` refuse with the CAP-013 message (exit 4) while the cluster is protected, whatever Capella itself enforces. There is no `--ignore-protection`.

## Implementation notes (as built)

- `capellactl scope delete CLUSTER BUCKET SCOPE` and `capellactl collection delete CLUSTER BUCKET SCOPE COLLECTION` (both `[--project NAME]`, `cli/scope_cmds.py`). Like `bucket delete` (CAP-024) they show `- scope …`, what is lost and the dependent credentials, ask for the **name to be typed** (skipped with `--auto-approve`; refused without a terminal), and after the `DELETE` **remove the item from `capella.yaml`** so the next `apply` does not create it again (an emptied `collections:`/`scopes:` list is removed too).
- **AC2**: the scope's collections come from `GET …/scopes/{scopeName}`: `billing · 2 collections: invoices, refunds`, then `These collections and all their documents are deleted.`
- **AC3**: checked before any API call; exit 4, help topic `safety`.
- **AC4**: scopes and collections are prunable. In `apply --prune` each scope or collection delete shows the same details and asks for its name to be typed, before the usual `Apply N changes?` question (`cli/env.py::confirm_data_delete`, shared with buckets). A prune on a protected cluster is BLOCKED. `plan` lists them as unmanaged (CAP-025).
- **AC5**: a credential is listed when its `access[].resources.buckets[].scopes[]` names the scope (any collections) for a scope delete, or names the collection for a collection delete. Bucket-wide grants, and scope-wide grants for a collection delete, are not listed: they keep their access.
- **AC6**: `not found, nothing to do` also when the bucket or the scope is gone; the file is still brought in step.
- `destroy` is delivered by CAP-030.
