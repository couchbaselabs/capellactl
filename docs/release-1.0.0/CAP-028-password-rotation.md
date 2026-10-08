# CAP-028 — Password rotation

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E8 Database credentials | P0 | 3 | CAP-027, CAP-008 | Implemented |

## User story
As a **security-conscious operator**, I want to rotate a credential's password on demand, from my secret store or generated, so that rotation policies can be met without ever changing a password by accident.

## Context & discovery
- `PUT …/users/{userId}` accepts `password`; `204`.
- Capella never returns passwords, so a changed `${VAR}` value is **not** detectable as drift. Passwords change only on explicit rotation.
- Capella password rules (spec): at least 8 characters with an upper-case letter, a lower-case letter, a number and a special character, and none of `< > ; . * & | £` (`CreateDatabaseCredentialRequest.password`).

## Implementation details
```
capellactl credential update CLUSTER NAME --rotate-password
capellactl apply --rotate-passwords [--target credential/CLUSTER/NAME …]
```
- Source: the configured `${VAR}`/`${file:…}` value if present; otherwise a locally generated 32-character password meeting the rules (`secrets.choice`), saved via CAP-008.
- Supplied passwords are checked against the rules offline before any call.

## Acceptance criteria & tests

### AC1 — Rotate from configured secret
**Given** `password: ${ORDERS_APP_PASSWORD}`, **then** `--rotate-password` sends `PUT {password, access}` with `If-Match` (the access from capella.yaml: Capella removes every grant when `access` is left out) and prints `password rotated for orders_app` (no value).

| Test | Location | Verifies |
|---|---|---|
| `test_rotation_ac1_from_configured_secret` | `tests/scenario/test_rotation.py` | `assert_no_secret` |
| `test_rotation_ac1_keeps_access` | `tests/scenario/test_credential_access_kept.py` | Access unchanged after rotation |

### AC2 — Rotate with generated password
**Given** no configured password, **then** a generated password meeting the rules is sent and saved to the credentials file (overwrite of that credential's own file is allowed for rotation, keeping a `.bak` with mode `0600`).

| Test | Location | Verifies |
|---|---|---|
| `test_rotation_ac2_generated_saved_with_backup` | `tests/scenario/test_rotation.py` | |
| `test_password_gen_ac2_meets_rules` | `tests/unit/output/test_password_gen.py` | 10,000 samples |

### AC3 — Rules checked offline
**Given** a configured password `short`, **then** `validate` and `--rotate-password` exit 3 `password for orders_app does not meet Capella rules (min 8, upper, lower, digit, special, none of < > ; . * & | £)`; the value is not shown.

| Test | Location | Verifies |
|---|---|---|
| `test_rotation_ac3_weak_password_rejected` | `tests/unit/config/test_password_rules.py` | |
| `test_rotation_ac3_help_lists_rules` | same | Rules shown in `credential` help |

### AC4 — Never rotates implicitly
**Given** the value of `ORDERS_APP_PASSWORD` changes between runs, **then** a plain `apply` makes zero writes and prints `note: passwords are not compared; use --rotate-password to change them` once per run when any credential has a configured password.

| Test | Location | Verifies |
|---|---|---|
| `test_rotation_ac4_no_implicit_rotation` | `tests/scenario/test_rotation.py` | |

### AC5 — Bulk rotation with confirmation
**Given** `apply --rotate-passwords` with three credentials, **then** confirmation lists the three names, and three `PUT`s are sent; `--target` limits the set.

| Test | Location | Verifies |
|---|---|---|
| `test_rotation_ac5_bulk_with_target` | `tests/scenario/test_rotation.py` | |

### AC6 — Missing credential
**Given** `--rotate-password` for a credential that does not exist yet, **then** it is created (CAP-027) and no separate rotation call is made.

| Test | Location | Verifies |
|---|---|---|
| `test_rotation_ac6_missing_credential_created` | `tests/scenario/test_rotation.py` | |

## Out of scope
- Scheduled rotation (use cron/CI with this command).
- Pushing rotated passwords into external secret stores.

## Open questions
- None.

## Implementation notes (as built)
- 2026-10-07: a password-only `PUT {password}` left a credential with **no access** in Capella (seen live: `airline_app` had `access: []` after `--rotate-password`; the spec does not say an omitted `access` is kept). Rotation now always sends the access with the password, and the fake Capella clears access on a PUT without it.
- `RunContext.rotate_passwords` is set by `apply --rotate-passwords` and `credential update --rotate-password`. With it, every planned basic credential that exists becomes `~ credential CLUSTER/NAME   rotate password` (an UPDATE with `data["rotate"]`), so `--target` limits the set as usual (AC5). A missing credential is simply created (AC6).
- The `PUT` sends `{password}` with `If-Match`, together with `{access}` when access changed too. Afterwards the command prints `password rotated for NAME`.
- **AC2:** `output/password_gen.py` generates 32 characters with `secrets` and guarantees one of each class. The new password is written to the credential's file *before* it is sent, with the previous file kept as `<file>.bak` (mode 0600). If the `PUT` fails, the previous file is restored and the `.bak` removed, so the local file always holds the password Capella has.
- **AC3:** `config/crossref.py` checks every resolved configured password against the rules (`min 8, upper, lower, digit, special, none of < > ; . * & | £`), for every command that loads the file. The value is never shown.
- **AC4:** the note `note: passwords are not compared; use --rotate-password to change them` goes to stderr once per run when a credential has a configured password, and not during a rotation.
- **AC5:** the apply confirmation lists `Passwords to rotate:` with one `CLUSTER/NAME` per line before asking.
- `change_and_apply` no longer rewrites `capella.yaml` (or makes a `.bak`) when the file did not change, as in a rotate-only `credential update`.
- Forbidden characters added 2026-10-07: the spec's third rule (no `< > ; . * & | £`) was missed. The generator's special characters included `&`, `*` and `.`, so a generated rotation password could be refused by Capella; they were removed, and the offline check now rejects the forbidden characters. The rules are also listed in `credential --help`, `credential create --help` and `credential update --help` (`test_rotation_ac3_help_lists_rules`).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_rotation_ac1_from_configured_secret` (tests/scenario/test_rotation.py), `test_rotation_ac1_keeps_access` (tests/scenario/test_credential_access_kept.py) |
| AC2 | `test_rotation_ac2_generated_saved_with_backup`, `test_rotation_ac2_failed_send_restores_file`, `test_password_gen_ac2_meets_rules` (tests/unit/output/test_password_gen.py) |
| AC3 | `test_rotation_ac3_weak_password_rejected` (tests/unit/config/test_password_rules.py), `test_password_rules_ac3_each_rule`, `test_rotation_ac3_help_lists_rules` (tests/unit/config/test_password_rules.py) |
| AC4 | `test_rotation_ac4_no_implicit_rotation` |
| AC5 | `test_rotation_ac5_bulk_with_target` |
| AC6 | `test_rotation_ac6_missing_credential_created` |
