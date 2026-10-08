# CAP-039 — Create a project from the CLI

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E2 Projects | P0 | 3 | CAP-009, CAP-036, CAP-038 | Implemented |

## User story
As an **operator**, I want to create a Capella project with one command and have capellactl write `capella.yaml` for it, so that I can deploy clusters into a new project without editing YAML.

## Context & discovery
- Until now a project could only be created by `apply` when capella.yaml named a project that did not exist, which meant editing the file by hand (ruled out by CAP-038).
- `POST /v4/organizations/{organizationId}/projects` → `201 {id}`; body `name*` (≤ 128 characters), `description` (≤ 256). Roles: Organization Owner or Project Creator.
- Capella allows two projects with the same name, but capellactl finds projects by name, so `project create` refuses a name that is already used.
- One capella.yaml can describe several projects (CAP-040); a new project is appended to it.

## Implementation details
```
capellactl project create NAME [--description TEXT]
capellactl --config envs/qa.yaml project create nova-qa
```
Flow: check the name in Capella → check the target file → ask for a description if none was given (interactive) → show `+ project NAME` → ask once → `POST …/projects` → write capella.yaml for the new project (no clusters yet, with a pointer to `capellactl cluster create`) → print the next step.

## Acceptance criteria & tests

### AC1 — Create interactively
**Given** no capella.yaml in the folder, **when** `capellactl project create nova-qa` runs and the operator enters a description and confirms, **then** one `POST …/projects` is sent with `{name, description}`, capella.yaml is written for `nova-qa` with `clusters: []`, and the output ends with `Next: capellactl cluster create NAME`.

| Test | Location | Verifies |
|---|---|---|
| `test_project_create_ac1_interactive` | `tests/scenario/test_project_create.py` | |

### AC2 — Non-interactive
**Given** `--auto-approve --description …`, **then** the project is created without prompts. **Given** no terminal and no `--auto-approve`, **then** exit 1 and nothing is created or written.

| Test | Location | Verifies |
|---|---|---|
| `test_project_create_ac2_auto_approve` | `tests/scenario/test_project_create.py` | |
| `test_project_create_ac2_needs_auto_approve` | same | |

### AC3 — Name already used
**Given** a project with that name already exists, **then** exit 4 with `project nova-qa already exists; to add it to capella.yaml run 'capellactl import --project nova-qa'`, and nothing is created.

| Test | Location | Verifies |
|---|---|---|
| `test_project_create_ac3_existing_name` | `tests/scenario/test_project_create.py` | |

### AC4 — Adds the project to the existing file
**Given** capella.yaml in the folder describes project `nova-dev`, **then** `project create nova-qa` creates the project and appends it to capella.yaml (a `.bak` is kept); `nova-dev` and its clusters are unchanged. **Given** `--config other.yaml`, **then** that file is used instead. *(Revised by CAP-040: one capella.yaml holds several projects.)*

| Test | Location | Verifies |
|---|---|---|
| `test_project_create_ac4_adds_to_existing_file` | `tests/scenario/test_project_create.py` | |

### AC5 — Ready for clusters
**Given** a project just created, **then** `plan` reports no changes and `cluster create` deploys into it using the same file.

| Test | Location | Verifies |
|---|---|---|
| `test_project_create_ac5_then_cluster_create` | `tests/scenario/test_project_create.py` | |

### AC6 — Discoverable
**Given** `capellactl project --help`, **then** `create` is listed, and the README step-by-step shows creating and listing projects.

| Test | Location | Verifies |
|---|---|---|
| `test_project_create_ac6_help_and_readme` | `tests/scenario/test_project_create.py` | |

## Out of scope
- Deleting projects (CAP-010).
- Several projects in one file.

## Open questions
- None.

## Implementation notes (as built)
- Built after a user noticed `project --help` had no `create`. `project apply`'s help text, which said "Create or update only the project from the config file", was also misleading and now reads "Apply the project settings recorded in capella.yaml".
- If capella.yaml in the folder already describes the same (not yet created) project, the project is created and the file is kept as it is, so clusters recorded in it are not lost; `capellactl apply` then deploys them.
- `import` on an organization with no projects now points to `capellactl project create NAME` instead of the Capella UI.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_project_create_ac1_interactive` (tests/scenario/test_project_create.py) |
| AC2 | `test_project_create_ac2_auto_approve` (tests/scenario/test_project_create.py)<br>`test_project_create_ac2_needs_auto_approve` (tests/scenario/test_project_create.py) |
| AC3 | `test_project_create_ac3_existing_name` (tests/scenario/test_project_create.py) |
| AC4 | `test_project_create_ac4_adds_to_existing_file` (tests/scenario/test_project_create.py) |
| AC5 | `test_project_create_ac5_then_cluster_create` (tests/scenario/test_project_create.py) |
| AC6 | `test_project_create_ac6_help_and_readme` (tests/scenario/test_project_create.py) |
