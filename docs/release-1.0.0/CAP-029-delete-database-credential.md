# CAP-029 — Delete database credential

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E8 Database credentials | P0 | 1 | CAP-027 | Implemented |

## User story
As an **operator**, I want to remove a credential that is no longer needed, so that unused access is revoked.

## Context & discovery
- `DELETE …/clusters/{clusterId}/users/{userId}` → `204`.

## Implementation details
`capellactl credential delete CLUSTER NAME`; also via `apply --prune` and `destroy`.

## Acceptance criteria & tests

### AC1 — Delete
**Given** `reporting_ro` exists, **then** the confirmation summarises its access, and `DELETE …/users/{id}` is sent.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_delete_ac1_delete` | `tests/scenario/test_credential_delete.py` | |
| `test_endpoints_ac1_delete_credential_contract` | `tests/contract/test_endpoints_credential.py` | |

### AC2 — Local secret file left in place
**Given** a saved credentials file exists for it, **then** the file is not deleted and the command prints `local secret file kept: <path> (delete it if no longer needed)`.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_delete_ac2_secret_file_kept` | `tests/scenario/test_credential_delete.py` | |

### AC3 — Prune only when asked
**Given** the credential is removed from the file, **then** `apply` does not delete it; `apply --prune` does.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_delete_ac3_prune_only` | `tests/scenario/test_credential_delete.py` | |

### AC4 — Idempotent re-run
**Given** AC1 completed, **then** re-running prints `not found, nothing to do`, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_delete_ac4_rerun_noop` | `tests/scenario/test_credential_delete.py` | |

## Out of scope
- None.

## Open questions
- None.

## Implementation notes (as built)
- `credential delete CLUSTER NAME` (`cli/credential_cmds.py`) shows `- credential CLUSTER/NAME  <access summary>`, asks y/N (or `--auto-approve`), sends `DELETE …/users/{id}` with the id from the list response, and removes the entry from `capella.yaml` (`.bak` kept).
- **AC2:** the local file of a generated password is never deleted. The command, and `apply --prune`, print `local secret file kept: <path> (delete it if no longer needed)`.
- **AC3:** `CredentialReconciler.prunable`: `apply --prune` deletes basic credentials that the file no longer declares. Advanced credentials (`userRoles`), which `import` writes only as comments, are listed as `= credential … (advanced credential: not managed by capellactl 1.0, left unchanged)` and never pruned.
- `destroy` is still CAP-030; it will reuse this reconciler's delete.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_credential_delete_ac1_delete` (tests/scenario/test_credential_delete.py), `test_endpoints_ac1_delete_credential_contract` (tests/contract/test_endpoints_credential.py) |
| AC2 | `test_credential_delete_ac2_secret_file_kept` |
| AC3 | `test_credential_delete_ac3_prune_only` |
| AC4 | `test_credential_delete_ac4_rerun_noop` |
