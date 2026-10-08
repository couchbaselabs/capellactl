# CAP-027 — Ensure database credential (basic access)

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E8 Database credentials | P0 | 5 | CAP-025, CAP-008 | Implemented |

## User story
As an **application team lead**, I want application credentials created with least-privilege read/write access to specific buckets, scopes or collections, so that each service gets only the access it needs, the same way in every environment.

## Context & discovery

| Operation | Endpoint | Success |
|---|---|---|
| List | `GET …/clusters/{clusterId}/users` | 200 |
| Get | `GET …/users/{userId}` | 200 + `ETag`; fields `id, name, audit, access, userRoles` — **no password** |
| Create | `POST …/clusters/{clusterId}/users` | 201 `{id, password}` |
| Update | `PUT …/users/{userId}` | 204; body `access`, `password`, `userRoles`; `412` on stale ETag |

- Create body: `name*` (2–128 chars, no spaces), `password` (generated if omitted), `credentialType` (`basic` default / `advanced`), `access[]` (`privileges*`, `resources.buckets[].{name*, scopes[].{name*, collections[]: string}}`), `userRoles` (advanced only).
- **Basic** credentials accept only `read`, `write`, `data_reader`, `data_writer` (`read` = `data_reader`, `write` = `data_writer`). Omitting `resources` grants access to **all buckets**.

## Implementation details
```yaml
databaseCredentials:
  - name: orders_app
    password: ${ORDERS_APP_PASSWORD}
    access:
      - privileges: [data_reader, data_writer]
        resources:
          buckets:
            - name: orders
              scopes:
                - name: inventory
                  collections: [items, suppliers]
```
- Comparison: privileges canonicalised and sorted; bucket/scope/collection names sorted.
- Update sends `{access}` only; password handling is CAP-028 and CAP-008.

## Acceptance criteria & tests

### AC1 — Create with supplied password
**Given** `orders_app` missing and `ORDERS_APP_PASSWORD` set, **then** `+ credential nova-dev-01/orders_app  read+write · orders/inventory/{items,suppliers}`; `POST` body has `name`, `password`, `credentialType: "basic"`, `access`; the password is not in plan or output.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_ac1_create_supplied_password` | `tests/scenario/test_credential.py` | `assert_no_secret` |
| `test_endpoints_ac1_credential_contract` | `tests/contract/test_endpoints_credential.py` | |

### AC2 — Create with generated password
**Given** no `password`, **then** the `POST` omits it and the 201 password is saved per CAP-008 AC2.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_ac2_generated_password_saved` | `tests/scenario/test_credential.py` | |

### AC3 — Access normalisation
**Given** Capella has `privileges: ["read","write"]` and buckets in another order, and the file has `[data_writer, data_reader]`, **then** `=`, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_normalize_ac3_equivalent_access` | `tests/unit/resources/test_credential.py` | |

### AC4 — Update access only
**Given** `orders/inventory` changes from `[data_reader]` to `[data_reader, data_writer]`, **then** `~ credential … orders/inventory: read → read+write` and `PUT {access}` with `If-Match`; the body never contains `password`.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_ac4_update_access_without_password` | `tests/scenario/test_credential.py` | |
| `test_credential_ac4_access_removed_in_capella_is_restored` | `tests/scenario/test_credential_access_kept.py` | Empty access in Capella → `~` update, not blocked |

### AC5 — Broad access warning
**Given** an access entry without `resources`, **then** `validate` warns `grants access to ALL buckets` and the plan line ends with `(all buckets)`.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_ac5_all_buckets_warning` | `tests/scenario/test_credential.py` | |

### AC6 — Unsupported privileges and types
**Given** `privileges: [queryManage]`, **then** `validate` exits 3 `basic credentials support read/write only; advanced credentials are planned for 1.1`. **Given** an existing `advanced` credential with the same name, **then** BLOCKED.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_validate_ac6_privilege_rejected` | `tests/unit/config/test_credential_rules.py` | |
| `test_credential_ac6_existing_advanced_blocked` | `tests/scenario/test_credential.py` | |

### AC7 — Ordering after data model
**Given** a new bucket, scope, collection and credential, **then** the credential `POST` is the last write for that cluster.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_ac7_created_last` | `tests/scenario/test_credential.py` | |

### AC8 — Idempotent re-run, password never re-sent
**Given** AC1 completed, **then** a re-run makes zero writes even though a password is configured.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_ac8_rerun_zero_writes` | `tests/scenario/test_credential.py` | |
| `test_credential_ac8_integration_connect` | `tests/integration/test_credentials.py` | SDK connects with the credential and reads `orders.inventory.items` |

## Out of scope
- Advanced credentials (`userRoles`), database roles (`/roles`) and privileges listing (`/privileges`) — 1.1.

## Open questions
- Does Capella return `409` for a duplicate credential name? (Assumed, per CAP-004 AC3.)

## Implementation notes (as built)
- 2026-10-07: a credential with `access: []` and no `userRoles` used to be reported as advanced and BLOCKED. It is a basic credential whose access was removed (for example by the rotation bug fixed in CAP-028), so `plan` now shows `~ credential …` and `apply` restores the access from capella.yaml. Only `userRoles` (or `credentialType: advanced`) marks an advanced credential.
- `resources/credential.py` (`CredentialReconciler`, kind `credential`, key `CLUSTER/NAME`) replaces the deferred placeholder and is the last child of the cluster, so its writes follow the data model it grants access to (AC7).
- **Comparison (AC3):** access is flattened to one privilege set per resource (all buckets, `bucket`, `bucket/scope`, `bucket/scope/collection`), with `read`/`write` mapped to `data_reader`/`data_writer`. Capella's grouping and ordering of grants therefore never show as a change. The plan summary reads `read+write · orders/inventory/{items,suppliers}`; grants on all buckets come last and read `· (all buckets)` (AC5).
- **AC4:** the update is `PUT {access}` with `If-Match` from a fresh `GET`. It never contains the password. Change lines use the generic plan renderer, so values are quoted: `orders/inventory:  "read" → "read+write"`.
- **AC2:** with no `password`, the credentials file is checked *before* the `POST` (CAP-008 AC3), then written from the 201 response. `credentialsOutput` is resolved relative to the config file's directory. The command prints `password saved to .capellactl/credentials/<cluster>.<name>.json`, plus the CAP-008 git warning when the directory is not ignored.
- **AC6:** `validate` reports `basic credentials support read/write only; advanced credentials are planned for 1.1` for a privilege outside the schema enum. An existing credential with `userRoles`, `credentialType: advanced` or no access is BLOCKED with topic `credentials`.
- The tool-only `external: true` bucket key is stripped from the API body.
- **Depends on CAP-025:** scopes and collections are still deferred. A credential that names a scope or collection not yet in Capella is sent as declared; create it first (Capella UI) or wait for CAP-025. Open question: does Capella reject access to a non-existent scope/collection? It's checked in the CAP-032 nightly run.
- `init` validated its draft with a placeholder password that broke Capella's password rules (CAP-028 AC3). The placeholder now meets them.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_credential_ac1_create_supplied_password` (tests/scenario/test_credential.py), `test_credential_ac1_summary_and_body` (tests/unit/resources/test_credential.py), `test_endpoints_ac1_credential_contract` (tests/contract/test_endpoints_credential.py) |
| AC2 | `test_credential_ac2_generated_password_saved`, `test_credential_ac2_existing_secret_file_blocks_create` |
| AC3 | `test_credential_normalize_ac3_equivalent_access`, `test_credential_normalize_ac3_grouping_does_not_matter` |
| AC4 | `test_credential_ac4_update_access_without_password`, `test_credential_ac4_changes_per_resource`, `test_credential_ac4_access_removed_in_capella_is_restored` (tests/scenario/test_credential_access_kept.py) |
| AC5 | `test_credential_ac5_all_buckets_warning` |
| AC6 | `test_credential_validate_ac6_privilege_rejected`, `test_credential_validate_ac6_basic_privileges_accepted` (tests/unit/config/test_credential_rules.py), `test_credential_ac6_existing_advanced_blocked` |
| AC7 | `test_credential_ac7_created_last` (stub scopes/collections), `test_credential_ac7_after_bucket_in_real_tree` |
| AC8 | `test_credential_ac8_rerun_zero_writes`; `test_credential_ac8_integration_connect` (tests/integration/test_credentials.py, nightly) |
