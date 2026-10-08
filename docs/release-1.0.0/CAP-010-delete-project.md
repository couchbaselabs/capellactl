# CAP-010 — Delete project

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E2 Projects | P0 | 2 | CAP-009 | Implemented |

## User story
As an **operator**, I want to delete a project safely, so that I can tear down environments without deleting the wrong thing or leaving orphans.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Delete | `DELETE /v4/organizations/{organizationId}/projects/{projectId}` | 204 | `409` documented (project not empty) |
| List clusters | `GET …/projects/{projectId}/clusters` | 200 | Used for the emptiness check |

## Implementation details
`capellactl project delete NAME [--cascade] [--auto-approve]`. Without `--cascade` the tool checks for clusters itself before calling the API, so the user gets a precise message rather than a generic `409`. With `--cascade`, it builds a delete plan of every child (reverse dependency order) using the same reconcilers as `destroy` (CAP-030).

## Acceptance criteria & tests

### AC1 — Delete an empty project
**Given** `nova-dev` exists with no clusters, **when** `project delete nova-dev` is confirmed by typing `nova-dev`, **then** `DELETE …/projects/{id}` is sent and the command prints `deleted project nova-dev`.

| Test | Location | Verifies |
|---|---|---|
| `test_project_delete_ac1_empty_project` | `tests/scenario/test_project_delete.py` | |

### AC2 — Absent is a no-op
**Given** no project named `nova-dev`, **then** `project nova-dev not found, nothing to do`, exit 0, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_project_delete_ac2_absent_noop` | `tests/scenario/test_project_delete.py` | |

### AC3 — Non-empty is blocked without cascade
**Given** the project contains cluster `nova-dev-01`, **then** `project nova-dev contains 1 cluster (nova-dev-01). Delete it first or pass --cascade.`, exit 4, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_project_delete_ac3_non_empty_blocked` | `tests/scenario/test_project_delete.py` | |

### AC4 — Cascade
**Given** `--cascade`, **then** the plan lists every child with `-` in reverse dependency order, a cluster with deletion protection is `!` BLOCKED (exit 4, zero writes), and otherwise children are deleted and waited on before the project `DELETE`.

| Test | Location | Verifies |
|---|---|---|
| `test_project_delete_ac4_cascade_order` | `tests/scenario/test_project_delete.py` | Order of writes |
| `test_project_delete_ac4_cascade_respects_protection` | same | |

### AC5 — Confirmation by typing the name
**Given** an interactive session, **then** the prompt is `Type the project name to confirm deletion:`; any other input cancels with zero writes. `--auto-approve` skips it.

| Test | Location | Verifies |
|---|---|---|
| `test_project_delete_ac5_wrong_name_cancels` | `tests/scenario/test_project_delete.py` | |

### AC6 — API 409 surfaced clearly
**Given** the API still returns `409` (for example an App Service the tool does not manage), **then** `Capella refused: project is not empty` plus the API `hint`, exit 1.

| Test | Location | Verifies |
|---|---|---|
| `test_project_delete_ac6_api_409_message` | `tests/scenario/test_project_delete.py` | |

### AC7 — Idempotent re-run
**Given** AC1 has run, **then** running it again prints `not found, nothing to do`, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_project_delete_ac7_rerun_noop` | `tests/scenario/test_project_delete.py` | |

### AC8 — capella.yaml follows the deletion
**Given** the deleted project is in capella.yaml, **then** it is removed from the file (a `.bak` is kept) so a later `apply` does not recreate it; other projects are unchanged. *(Added after CAP-038/CAP-040: capella.yaml is tool-owned and holds several projects.)*

| Test | Location | Verifies |
|---|---|---|
| `test_project_delete_ac8_removed_from_file` | `tests/scenario/test_project_delete.py` | |

## Out of scope
- Deleting resources the tool does not manage (App Services, etc.) as part of `--cascade`.

## Open questions
- Which resource types besides clusters make the project `409`? Confirm in sandbox and list them in the error hint.

## Implementation notes (as built)
- `capellactl project delete NAME [--cascade] [--discard-snapshots]`. The project is found by the `id` recorded in capella.yaml when there is one, otherwise by name; several projects with that name are BLOCKED.
- `--cascade` deletes the project's clusters directly (provisioned via `DELETE …/clusters/{id}?retainsnapshotbackups=`, free tier via `DELETE …/clusters/freeTier/{id}`), waits for each to be gone, then deletes the project. Any cluster with deletion protection blocks the whole command before anything is deleted. Full cluster deletion with its own story and options is CAP-014.
- With `--no-wait` and clusters to delete, the project is left in place and the command says to run it again once the clusters are gone (Capella refuses to delete a project that still has clusters).
- AC8 was added: the project is removed from capella.yaml (with a `.bak`); a file with no projects left (`projects: []`) is still valid.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_project_delete_ac1_empty_project` (tests/scenario/test_project_delete.py) |
| AC2 | `test_project_delete_ac2_absent_noop` (tests/scenario/test_project_delete.py) |
| AC3 | `test_project_delete_ac3_non_empty_blocked` (tests/scenario/test_project_delete.py) |
| AC4 | `test_project_delete_ac4_cascade_order` (tests/scenario/test_project_delete.py)<br>`test_project_delete_ac4_cascade_respects_protection` (tests/scenario/test_project_delete.py) |
| AC5 | `test_project_delete_ac5_wrong_name_cancels` (tests/scenario/test_project_delete.py) |
| AC6 | `test_project_delete_ac6_api_409_message` (tests/scenario/test_project_delete.py) |
| AC7 | `test_project_delete_ac7_rerun_noop` (tests/scenario/test_project_delete.py) |
| AC8 | `test_project_delete_ac8_removed_from_file` (tests/scenario/test_project_delete.py) |
