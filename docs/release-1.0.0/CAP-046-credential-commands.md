# CAP-046 — Database credential commands: list, get, create, update

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E8 Database credentials | P0 | 3 | CAP-027, CAP-038 | Implemented |

## User story
As an **application team lead**, I want to see, add and change database credentials with `capellactl credential …` commands, without editing capella.yaml by hand, so that granting an application access is one reviewed command, the same way buckets and clusters are managed (CAP-038).

## Context & discovery
- CAP-027 covers the reconciler (`plan`/`apply`), CAP-028 the `--rotate-password` flag of `credential update`, and CAP-029 `credential delete`. Until this story, `credential list | get | create | update` existed only as stubs, and no story covered them. The [API coverage report](API-COVERAGE.md) found the gap.
- Endpoints (Management API v4.0, *Database Credentials*): `GET …/clusters/{clusterId}/users`, `GET …/users/{userId}` (never returns the password), plus the CAP-027 writes through `apply`.
- The CLI follows the bucket commands (CAP-023): `create`/`update` validate → plan → confirm → write capella.yaml → apply; `--no-apply` only records the change.

## Implementation details
```
capellactl credential list CLUSTER
capellactl credential get CLUSTER NAME
capellactl credential create CLUSTER NAME [--privileges read|write|read+write] (--bucket B [--scope S [--collection C …]] | --all-buckets)
                                          [--password-env VAR | --password-file PATH] [--no-apply]
capellactl credential update CLUSTER NAME [access flags as for create] [--password-env VAR | --password-file PATH]
                                          [--rotate-password] [--no-apply]
```
- The access flags describe **one** grant. Credentials with several grants are changed in capella.yaml and applied with `apply`.
- `--privileges` defaults to `read` (least privilege). Either `--bucket` or an explicit `--all-buckets` is required.
- With no password flag, Capella generates the password, which is saved per CAP-008 AC2.

## Acceptance criteria & tests

### AC1 — List
**Given** a cluster with a basic credential `orders_app` (declared in the file) and an advanced credential `dba`, **then** `credential list nova-dev-01` prints `S.NO NAME TYPE ACCESS IN FILE` rows with `1 orders_app basic read+write · orders yes` and `2 dba advanced userRoles -`. `-o json` prints the API objects. No password is shown.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_cli_ac1_list` | `tests/scenario/test_credential_cli.py` | |

### AC2 — Get
**Given** `orders_app` exists, **then** `credential get nova-dev-01 orders_app` shows id, name, type and each access grant, and the location (never the value) of a saved generated password. An unknown name exits 1 with `credential nova-dev-01/NAME not found`.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_cli_ac2_get` | `tests/scenario/test_credential_cli.py` | `assert_no_secret` |

### AC3 — Create records and applies
**Given** `credential create nova-dev-01 orders_app --privileges read+write --bucket orders --scope inventory --password-env ORDERS_APP_PASSWORD`, **then** capella.yaml gains the entry with `password: ${ORDERS_APP_PASSWORD}` and `access: [{privileges: [data_reader, data_writer], resources: {buckets: [{name: orders, scopes: [{name: inventory}]}]}}]`, and one `POST` is sent. A name already in the file exits 4. Missing `--bucket`/`--all-buckets` exits 3. A credential that already exists in Capella with the same access is adopted with zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_cli_ac3_create_records_and_applies` | `tests/scenario/test_credential_cli.py` | |
| `test_credential_cli_ac3_create_guards` | `tests/scenario/test_credential_cli.py` | |

### AC4 — Update access
**Given** `orders_app` with one grant, **then** `credential update nova-dev-01 orders_app --privileges read --bucket orders` replaces the grant in the file and sends `PUT {access}`. A credential with several grants exits 3 and points to capella.yaml + `apply`. A credential not in the file exits 3. No flags exits 3 with `nothing to change`.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_cli_ac4_update_access` | `tests/scenario/test_credential_cli.py` | |
| `test_credential_cli_ac4_update_guards` | `tests/scenario/test_credential_cli.py` | |

### AC5 — Record only
**Given** `--no-apply`, **then** create and update change capella.yaml only (zero writes to Capella) and print `Not applied (--no-apply)`.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_cli_ac5_no_apply` | `tests/scenario/test_credential_cli.py` | |

### AC6 — Idempotent
**Given** AC3 completed, **then** `plan --detailed-exitcode` exits 0 and `apply` makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_credential_cli_ac6_rerun_zero_writes` | `tests/scenario/test_credential_cli.py` | |

## Out of scope
- Advanced credentials (`userRoles`) and custom database roles (1.1).
- Several access grants through flags (use capella.yaml + `apply`).

## Open questions
- None.

## Implementation notes (as built)
- `cli/credential_cmds.py` replaces the `credential` stub group. `create`/`update` reuse `change_and_apply` (validate → plan → confirm → write → apply), targeting `credential/CLUSTER/NAME`.
- `--privileges` maps `read` → `[data_reader]`, `write` → `[data_writer]`, `read+write` → both. `--scope` needs `--bucket`, `--collection` needs `--scope`, and `--bucket` and `--all-buckets` are exclusive. `--password-env`/`--password-file` record `${VAR}`/`${file:PATH}`; both at once is refused.
- `update` with access flags replaces the single grant. With a password flag it only records the new reference; the password changes only with `--rotate-password` (CAP-028).
- `list` shows `userRoles` in the ACCESS column for advanced credentials. `get` shows where a generated password is saved, never its value.
- `credential --help` and `credential create --help` show worked examples for each access level (`B.*.*` with `--bucket`, `B.S.*` with `--scope`, `B.S.C` with `--collection`, `--all-buckets`) and each password source (generated and saved to `credentialsOutput`, `--password-env`, `--password-file`). There is no default password, and no flag takes a literal password, so it never lands in shell history.
- README *Step by step* has a new step 9 (credentials), covered by `test_readme_walkthrough_steps`; later steps are renumbered.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_credential_cli_ac1_list` (tests/scenario/test_credential_cli.py) |
| AC2 | `test_credential_cli_ac2_get` |
| AC3 | `test_credential_cli_ac3_create_records_and_applies`, `test_credential_cli_ac3_create_guards` |
| AC4 | `test_credential_cli_ac4_update_access`, `test_credential_cli_ac4_update_guards` |
| AC5 | `test_credential_cli_ac5_no_apply` |
| AC6 | `test_credential_cli_ac6_rerun_zero_writes` |
