# CAP-064 — Custom database roles & advanced credentials

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E11 Data access & tools | P0 | 5 | CAP-027, CAP-046 | Not started |

## User story
As an **operator**, I want to define database roles with exactly the privileges an application needs and assign
them to database credentials, so that I can grant least privilege without the three fixed access levels of 1.0.0.

## Context & discovery
- 1.0.0 creates **basic** credentials only (CAP-027: `read`, `write`, `read/write` per bucket/scope). The spec also
  accepts `credentialType: advanced` with `userRoles` (role names) on `POST …/users` and `PUT …/users/{userId}`.
  00-architecture.md §14 listed both as "Not in 1.0.0".
- Custom roles are cluster-scoped. `access[]` has the same shape as a credential's: `privileges` plus
  `resources.buckets[]` (bucket, scopes, collections).

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| List privileges | `GET …/clusters/{clusterId}/privileges` | 200 | `name`, `group` (`data`, `query`, `analytics`, `fts`, `eventing`, `global`), `resources` |
| List roles | `GET …/clusters/{clusterId}/roles` | 200 | Paginated; `id`, `name`, `description`, `access[]`, `audit` |
| Create role | `POST …/clusters/{clusterId}/roles` | 201 | `name` (required), `description`, `access[]` → `id` |
| Get role | `GET …/clusters/{clusterId}/roles/{roleId}` | 200 | |
| Update role | `PUT …/clusters/{clusterId}/roles/{roleId}` | 204 | `description`, `access[]`; the name is immutable |
| Delete role | `DELETE …/clusters/{clusterId}/roles/{roleId}` | 204 | |

## Design

### Commands
```
capellactl db-role privileges CLUSTER [--group data|query|analytics|fts|eventing|global]
capellactl db-role list       CLUSTER
capellactl db-role get        CLUSTER NAME
capellactl db-role create     CLUSTER NAME --privilege P … [--bucket B[.SCOPE[.COLLECTION]] …] [--description TEXT]
capellactl db-role update     CLUSTER NAME [--privilege P …] [--bucket …] [--description TEXT]
capellactl db-role delete     CLUSTER NAME
capellactl credential create  CLUSTER NAME --role ROLE …        # advanced credential (new flag)
capellactl credential update  CLUSTER NAME --role ROLE …
```
Examples:
```
capellactl db-role privileges nova-dev-01 --group data
capellactl db-role create nova-dev-01 orders-reader --privilege data_reader --bucket orders
capellactl credential create nova-dev-01 orders_app --role orders-reader
```

### capella.yaml
```yaml
clusters:
  - name: nova-dev-01
    databaseRoles:
      - name: orders-reader
        description: Read-only access to orders
        access:
          - privileges: [data_reader]
            resources: {buckets: [{name: orders}]}
    databaseCredentials:
      - name: orders_app
        roles: [orders-reader]      # advanced credential: sent as credentialType advanced + userRoles
```
`access` and `roles` are mutually exclusive on one credential (exit 3). Roles reconcile before credentials and are
deleted after them (§4.2: `buckets → scopes → collections → database roles → database credentials`).

### Where the code goes
- `cli/db_role_cmds.py` (new); `resources/database_role.py` (new reconciler, prunable); `resources/credential.py`
  learns `roles`; `api/endpoints.py` gains the six operations; the fake Capella and
  `docs/api/management-api-v4.0-responses.json` are extended until `test_fake_parity.py` passes.

## Acceptance criteria & tests

### AC1 — Create a role
**Given** `db-role create nova-dev-01 orders-reader --privilege data_reader --bucket orders`, **then** one
`POST …/roles` is sent with that `access`, capella.yaml records it, and `plan` reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_db_role_ac1_create_body` | `tests/scenario/test_db_roles.py` | Body, file, no drift |

### AC2 — Unknown privileges are refused before any write
**Given** a privilege not in `GET …/privileges`, **then** exit 3 naming it and the closest match, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_db_role_ac2_unknown_privilege` | `tests/scenario/test_db_roles.py` | |

### AC3 — Update and idempotency
**Given** a changed `access` or description, **then** `plan` shows `~ database role nova-dev-01/orders-reader` with
the field diff and `apply` sends one `PUT`. A rename is shown as BLOCKED (exit 4). A second run makes zero
`POST`/`PUT`/`DELETE` calls.

| Test | Location | Verifies |
|---|---|---|
| `test_db_role_ac3_update` | `tests/scenario/test_db_roles.py` | |
| `test_db_role_ac3_rerun_zero_writes` | same | |

### AC4 — Assign roles to a credential
**Given** `credential create nova-dev-01 orders_app --role orders-reader`, **then** the `POST …/users` body has
`credentialType: advanced` and `userRoles: [orders-reader]`, the generated password is saved as in CAP-027, and
`credential get` shows the roles. A role that does not exist is refused with exit 3.

| Test | Location | Verifies |
|---|---|---|
| `test_db_role_ac4_advanced_credential` | `tests/scenario/test_db_roles.py` | Body, output, password file |
| `test_db_role_ac4_unknown_role` | same | |

### AC5 — Delete guarded by use
**Given** a role assigned to credentials, **then** `db-role delete` lists them and refuses (exit 4) unless the
credentials are changed first; an unused role is deleted after confirmation. Re-running prints
`not found, nothing to do`.

| Test | Location | Verifies |
|---|---|---|
| `test_db_role_ac5_delete_in_use_blocked` | `tests/scenario/test_db_roles.py` | |
| `test_db_role_ac5_delete` | same | Also the re-run no-op |

### AC6 — Environment commands and lists
**Given** roles in Capella, **then** `sync` writes them, `drift` lists unmanaged ones, `apply --prune` deletes them
(after the credentials that use them). `db-role list` prints `S.NO`, `NAME`, `PRIVILEGES`, `ID`.

| Test | Location | Verifies |
|---|---|---|
| `test_db_role_ac6_sync_round_trip` | `tests/scenario/test_db_roles.py` | |
| `test_db_role_ac6_drift_and_prune_order` | same | |
| `test_db_role_ac6_list_columns` | same | |

## Out of scope
- Built-in Couchbase Server roles other than through `userRoles` names.

## Open questions
- Does `userRoles` accept built-in role names (for example `data_reader[orders]`) as well as custom role names? The
  spec says "role names"; confirm in the sandbox before AC4 is written as code.
