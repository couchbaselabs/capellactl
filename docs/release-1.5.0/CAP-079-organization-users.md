# CAP-079 — Organization users

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E14 Organization administration | P1 | 5 | CAP-037, CAP-009 | Not started |

## User story
As an **organization owner**, I want to invite users and give them organization and project roles from capellactl,
so that onboarding and offboarding are scripted and reviewable.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Invite | `POST {org}/users` | 201 | `email` (required), `name`, `organizationRoles[]`, `resources[]` (`type: project`, `id`, `roles[]`) → `id` |
| List | `GET {org}/users` | 200 | Paginated; filter by `projectId`; `status` (`verified`, `not-verified`, `pending-primary`), `inactive`, `lastLogin` |
| Get | `GET {org}/users/{userId}` | 200 | |
| Update | `PATCH {org}/users/{userId}` | 200 | JSON-patch-like list: `op` (`add`, `remove`), `path`, `value` |
| Delete | `DELETE {org}/users/{userId}` | 204 | |

Organization roles: `organizationOwner`, `organizationMember`, `projectCreator`, `organizationBillingAdmin`,
`organizationBillingViewer`, `organizationReadOnly`. Project roles as listed by the spec (`projectOwner`,
`projectManager`, `projectViewer`, `projectDataReaderWriter`, `projectDataReader`).

## Design

### Commands
```
capellactl user list   [--project NAME]
capellactl user get    EMAIL
capellactl user create EMAIL [--name NAME] [--org-role R …] [--project-role PROJECT=ROLE[,ROLE] …]
capellactl user update EMAIL [--add-org-role R …] [--remove-org-role R …] [--add-project-role PROJECT=ROLE …] [--remove-project-role PROJECT=ROLE …]
capellactl user delete EMAIL
```
Example:
```
capellactl user create dev@example.com --org-role organizationMember --project-role nova=projectViewer
```
- Users are addressed by email; capellactl resolves the ID from `user list`.
- `update` builds the patch list from the flags and prints the before → after roles first.
- `delete` asks for the email to be typed, and refuses to delete the user that owns the API key in use or the last
  `organizationOwner` (exit 4).
- Imperative only: users are not declared in capella.yaml (people are managed by an identity process, not per
  environment file).
- Code: `cli/user_cmds.py`, five operations, fake Capella.

## Acceptance criteria & tests

### AC1 — Invite
**Given** the example, **then** one `POST {org}/users` with the email, `organizationRoles: [organizationMember]` and
`resources: [{type: project, id: <nova id>, roles: [projectViewer]}]`, and `invited dev@example.com (pending
verification)` is printed.

| Test | Location | Verifies |
|---|---|---|
| `test_user_ac1_invite` | `tests/scenario/test_org_users.py` | |

### AC2 — Idempotent
**Given** the user already exists with those roles, **then** `create` prints `already exists with these roles`, exit
0, zero writes; with different roles it points to `user update`.

| Test | Location | Verifies |
|---|---|---|
| `test_user_ac2_rerun_zero_writes` | `tests/scenario/test_org_users.py` | |

### AC3 — Update roles
**Given** `--add-project-role nova=projectManager --remove-project-role nova=projectViewer`, **then** one `PATCH` with
the two operations; an unknown role or project exits 3 before any write.

| Test | Location | Verifies |
|---|---|---|
| `test_user_ac3_update_roles` | `tests/scenario/test_org_users.py` | |
| `test_user_ac3_unknown_role_or_project` | same | |

### AC4 — Delete guards
**Given** the last organization owner or the caller's own user, **then** exit 4; otherwise typed confirmation and one
`DELETE`.

| Test | Location | Verifies |
|---|---|---|
| `test_user_ac4_delete_guards` | `tests/scenario/test_org_users.py` | |

### AC5 — List
**Given** users, **then** `list` prints `S.NO`, `NAME`, `EMAIL`, `ORG ROLES`, `STATUS`, `LAST LOGIN`, `ID`;
`--project` filters.

| Test | Location | Verifies |
|---|---|---|
| `test_user_ac5_list` | `tests/scenario/test_org_users.py` | |

## Out of scope
- Declaring users in capella.yaml; SSO and group mapping.

## Open questions
- Which `path` values does the `PATCH` accept (`/organizationRoles`, `/resources/{id}/roles`)? Confirm the exact
  shape in the sandbox before AC3 is coded.
