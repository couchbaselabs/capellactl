# CAP-080 — API keys

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E14 Organization administration | P1 | 5 | CAP-037, CAP-008 | Not started |

## User story
As an **organization owner**, I want to create, rotate and revoke Capella API keys from capellactl, so that CI
pipelines get narrowly scoped keys and keys are rotated on schedule without the UI.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Create | `POST {org}/apikeys` | 201 | `name` (required), `description`, `expiry` (days), `allowedCIDRs[]`, `organizationRoles[]`, `resources[]` (project roles) → `id`, `token` |
| List | `GET {org}/apikeys` | 200 | Paginated |
| Get | `GET {org}/apikeys/{ApiKeyId}` | 200 | Never returns the secret |
| Delete | `DELETE {org}/apikeys/{ApiKeyId}` | 204 | |
| Rotate | `POST {org}/apikeys/{ApiKeyId}/rotate` | 200 | Optional `secret` → `secretKey`, `token` |

The `token` is shown **once**. It is a secret under CAP-008: never printed to logs, never in `-o json` unless the
user asks for it with `--show-token`.

## Design

### Commands
```
capellactl apikey list
capellactl apikey get    NAME|ID
capellactl apikey create NAME [--org-role R …] [--project-role PROJECT=ROLE …] [--expiry-days N] [--allow-cidr CIDR …] [--save-profile NAME | --out FILE | --show-token]
capellactl apikey rotate NAME|ID [--save-profile NAME | --out FILE | --show-token]
capellactl apikey delete NAME|ID
```
Example:
```
capellactl apikey create ci-nova --project-role nova=projectManager --expiry-days 90 --allow-cidr 203.0.113.0/24 --save-profile ci
```
- The token goes to exactly one place: `--save-profile` stores it in the OS keychain as a CAP-037 profile,
  `--out` writes a 0600 file (as CAP-008 does for passwords), `--show-token` prints it once. With none of them the
  command refuses to run (exit 3), so a token is never lost or leaked by default.
- `delete` and `rotate` of the key the current profile is using are refused unless `--force`, because they would
  lock the caller out mid-command.
- Imperative only (keys are credentials, not environment state).
- Code: `cli/apikey_cmds.py`, five operations, fake Capella.

## Acceptance criteria & tests

### AC1 — Create and store
**Given** the example, **then** one `POST` with the project role, `expiry: 90` and the CIDR; the token is saved in the
keychain under profile `ci`; the output shows the key ID and expiry but not the token.

| Test | Location | Verifies |
|---|---|---|
| `test_apikey_ac1_create_save_profile` | `tests/scenario/test_api_keys.py` | `assert_no_secret` on all output |
| `test_apikey_ac1_out_file_mode` | same | 0600 file |

### AC2 — The token must go somewhere
**Given** `apikey create` without `--save-profile`, `--out` or `--show-token`, **then** exit 3 before any write.

| Test | Location | Verifies |
|---|---|---|
| `test_apikey_ac2_destination_required` | `tests/scenario/test_api_keys.py` | |

### AC3 — Rotate
**Given** `apikey rotate ci-nova --save-profile ci`, **then** one `POST …/rotate` and the profile's keychain entry is
replaced; the old token no longer works against the fake.

| Test | Location | Verifies |
|---|---|---|
| `test_apikey_ac3_rotate` | `tests/scenario/test_api_keys.py` | |

### AC4 — Guards
**Given** the key the current profile uses, **then** `delete` and `rotate` exit 4 without `--force`; an existing name
on `create` exits 4 pointing to `rotate`.

| Test | Location | Verifies |
|---|---|---|
| `test_apikey_ac4_guards` | `tests/scenario/test_api_keys.py` | |

### AC5 — List and get
**Given** keys, **then** `list` prints `S.NO`, `NAME`, `ROLES`, `EXPIRES`, `ID`; `get` adds the allowed CIDRs; no
output ever contains a token.

| Test | Location | Verifies |
|---|---|---|
| `test_apikey_ac5_list_get` | `tests/scenario/test_api_keys.py` | |

## Out of scope
- Scheduled rotation (users run `apikey rotate` from their scheduler).

## Open questions
- Is `expiry` in days (the spec's description) and does `-1` mean no expiry? Confirm before AC1 is coded.
