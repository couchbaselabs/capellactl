# CAP-009 — Ensure project (create & update)

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E2 Projects | P0 | 2 | CAP-005, CAP-006 | Implemented |

## User story
As an **operator**, I want `apply` to create my project if it is missing and correct its description if it differs, so that I never have to check the Capella UI first.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| List | `GET /v4/organizations/{organizationId}/projects` | 200 | Paginated |
| Get | `GET …/projects/{projectId}` | 200 + `ETag` | Fields `id, name, description, audit` |
| Create | `POST …/projects` | 201 `{id}` | Body `name*` (≤128), `description` (≤256). Roles: Organization Owner, Project Creator |
| Update | `PUT …/projects/{projectId}` | 204 | Body `name*`, `description`; `412` on stale ETag. Roles: Organization Owner, Project Owner |

- Capella does **not** enforce unique project names.

## Implementation details

Config:
```yaml
project:
  name: nova-dev
  description: Nova development environment
  # id: 2b5c…   # optional pin
```

`resources/project.py`: `observe` lists projects (or gets by pinned `id`); `diff` compares `description` (and `name` when `id` is pinned); `apply` → `POST` or `PUT` with `If-Match`.

CLI: `capellactl project list`, `project get NAME`, `project update NAME --description …` (reconciles only the project; `project apply` is a hidden alias).

## Acceptance criteria & tests

### AC1 — Create when missing
**Given** no project named `nova-dev`, **when** `apply --auto-approve` runs, **then** the plan shows `+ project nova-dev`, one `POST /v4/organizations/org-1/projects` is sent with `{"name":"nova-dev","description":"Nova development environment"}`, and the returned `id` is used as `projectId` for children.

| Test | Location | Verifies |
|---|---|---|
| `test_project_ac1_create_when_missing` | `tests/scenario/test_project.py` | Body and child path use new id |
| `test_endpoints_ac1_create_project_contract` | `tests/contract/test_endpoints_project.py` | |

### AC2 — Update description
**Given** the project exists with a different description, **then** the plan shows `~ project nova-dev  description: "old" → "Nova development environment"` and `PUT …/projects/{id}` is sent with `name`, `description` and `If-Match`.

| Test | Location | Verifies |
|---|---|---|
| `test_project_ac2_update_description_with_if_match` | `tests/scenario/test_project.py` | |

### AC3 — Description omitted is left alone
**Given** the file has no `description` and Capella has one, **then** no change is planned.

| Test | Location | Verifies |
|---|---|---|
| `test_project_ac3_omitted_description_untouched` | `tests/unit/resources/test_project.py` | |

### AC4 — Ambiguous name blocked
**Given** two projects named `nova-dev`, **then** `! project nova-dev  2 projects share this name (ids: p-1, p-2); add id: under project: to choose one`, exit 4, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_project_ac4_ambiguous_blocked` | `tests/scenario/test_project.py` | |

### AC5 — Pinned id: rename and not-found
**Given** `id: p-1` and the project's name is `nova-old`, **then** `~ project  name: "nova-old" → "nova-dev"`. **Given** `id: p-404` that does not exist, **then** exit 1 `project p-404 not found` and **no** project is created.

| Test | Location | Verifies |
|---|---|---|
| `test_project_ac5_pinned_id_rename` | `tests/scenario/test_project.py` | |
| `test_project_ac5_pinned_id_missing_never_creates` | same | Zero POSTs |

### AC6 — List and get
**Given** three projects, **then** `project list` prints a table with `ID, NAME, DESCRIPTION, CREATED` and `-o json` prints the API objects; `project get nova-dev` prints one.

| Test | Location | Verifies |
|---|---|---|
| `test_project_cli_ac6_list_table_and_json` | `tests/scenario/test_project_cli.py` | |
| `test_project_cli_ac6_get_by_name` | same | |

### AC7 — Idempotent re-run
**Given** AC1 has run, **when** `apply` runs again, **then** zero writes and exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_project_ac7_rerun_zero_writes` | `tests/scenario/test_project.py` | |

## Out of scope
- Project-level user/role assignments.

## Open questions
- None.

## Implementation notes (as built)
- Wrong name kind (2026-10-07): when a project name given to `project update`, `project get` or `--project` is not a project but is a cluster in capella.yaml, the error says `NAME is a cluster in project P, not a project` and shows the corrected command, instead of suggesting `import --project NAME`. Tests: `test_project_update_cluster_name_given_points_to_project`, `test_project_option_cluster_name_given_points_to_project` (tests/scenario/test_resource_verbs.py).
- Built together with the Skeleton so a project can be managed end to end. `project apply` reconciles only the project.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_project_ac1_create_when_missing` (tests/scenario/test_project.py) |
| AC2 | `test_project_ac2_update_description_with_if_match` (tests/scenario/test_project.py) |
| AC3 | `test_project_ac3_omitted_description_untouched` (tests/scenario/test_project.py) |
| AC4 | `test_project_ac4_ambiguous_blocked` (tests/scenario/test_project.py) |
| AC5 | `test_project_ac5_pinned_id_rename` (tests/scenario/test_project.py)<br>`test_project_ac5_pinned_id_missing_never_creates` (tests/scenario/test_project.py) |
| AC6 | `test_project_cli_ac6_list_table_and_json` (tests/scenario/test_project.py)<br>`test_project_cli_ac6_get_by_name` (tests/scenario/test_project.py) |
| AC7 | `test_project_ac7_rerun_zero_writes` (tests/scenario/test_project.py) |
