# CAP-078 — Organization settings

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E14 Organization administration | P2 | 1 | CAP-037 | Not started |

## User story
As an **organization owner**, I want to set my organization's sign-in subdomain from capellactl, so that the
organization's setup can be scripted with everything else.

## Context & discovery
- `PUT {org}/configuration` → 204. Body: `subdomain` (required). Optional `If-Match` header for optimistic
  concurrency. Needs Organization Owner.
- `GET {org}` (used since 1.0.0 by `validate`/`plan`) returns the organization's details.

## Design
```
capellactl org get
capellactl org update --subdomain NAME
```
Example:
```
capellactl org update --subdomain nova
```
- `org get` is a read of `GET {org}` (no new operation). `update` reads first, shows `~ organization  subdomain:
  old → new`, asks once, and sends `If-Match` with the version read, so a concurrent change is reported instead of
  overwritten (exit 1 with `changed by someone else; re-run`).
- Not declared in capella.yaml: the organization is shared by every file and profile.
- Code: `cli/org_cmds.py` (new), one operation, fake Capella.

## Acceptance criteria & tests

### AC1 — Update
**Given** `org update --subdomain nova`, **then** one `PUT {org}/configuration` with `subdomain: nova` and `If-Match`.

| Test | Location | Verifies |
|---|---|---|
| `test_org_ac1_update` | `tests/scenario/test_org.py` | |

### AC2 — Idempotent
**Given** the subdomain is already `nova`, **then** `no changes`, exit 0, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_org_ac2_rerun_zero_writes` | `tests/scenario/test_org.py` | |

### AC3 — Errors
**Given** a 412 (version changed), **then** exit 1 with the re-run hint; a 403, exit 1 naming the Organization Owner
role.

| Test | Location | Verifies |
|---|---|---|
| `test_org_ac3_errors` | `tests/scenario/test_org.py` | |

## Out of scope
- Organization creation and deletion (not in the API).

## Open questions
- Which characters does Capella allow in a subdomain? Validation is left to the API until documented.
