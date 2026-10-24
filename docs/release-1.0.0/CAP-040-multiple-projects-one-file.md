# CAP-040 — Several projects in one capella.yaml

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E2 Projects | P0 | 8 | CAP-002, CAP-005, CAP-036, CAP-038, CAP-039 | Implemented |

## User story
As an **operator**, I want one `capella.yaml` that holds all my projects with their clusters and everything in them, so that the whole organization is managed from one file and one set of commands.

## Context & discovery
- Release 1.0.0 started with "one file = one project". Users asked for one file for the organization (2026-10-05): `project create non-prod` refused because capella.yaml described project `demo`.
- Capella allows the same cluster name in different projects (for example `main` in `prod` and `non-prod`), so cluster names only need to be unique within a project.
- Files already written in the single-project form (`project:` + `clusters:`) must keep working; nobody should have to migrate by hand.

## Implementation details

### File format
```yaml
apiVersion: capellactl/v1
organizationId: 6af0…
projects:
  - name: demo
    description: Demo environment
    clusters:
      - name: demo-01
        …
  - name: non-prod
    clusters: []
```
The single-project form (`project:` + top-level `clusters:`) is still accepted. The first time a command writes the file, it is converted to `projects:` (a `.bak` copy is kept).

### Commands
| Command | Behaviour with several projects |
|---|---|
| `import [--project NAME…]` | Discovers every project by default (or the named ones) and adds those not yet in the file; projects already in the file are left alone (`sync` refreshes them). `--force` rewrites the whole file |
| `project create NAME` | Creates the project in Capella and adds it to the file |
| `project list` | Adds an `IN FILE` column |
| `sync [--project NAME…]` | Refreshes every project in the file (or the named ones) |
| `cluster create/update/scale/get/apply NAME [--project P]` | `--project` is needed only when the file has several projects and the choice is not obvious (create) or the name is used in several projects |
| `plan` / `apply` | Cover every project in the file; `--target cluster/PROJECT/NAME` also accepted |

## Acceptance criteria & tests

### AC1 — Multi-project file is validated
**Given** a file with `projects:` holding two projects and clusters, **then** `validate` succeeds and counts both. Errors name the full path (`projects[1].clusters[0].serviceGroups[0].numOfNodes`). Cluster names must be unique within a project but may repeat across projects; project names must be unique. A file with both `project:` and `projects:` is rejected.

| Test | Location | Verifies |
|---|---|---|
| `test_multi_ac1_validate_and_paths` | `tests/unit/config/test_multi_project.py` | |
| `test_multi_ac1_name_rules` | same | |

### AC2 — Single-project files keep working
**Given** a file in the single-project form, **then** validate, plan and apply behave exactly as before; the first write by a command converts it to `projects:` and keeps a `.bak`.

| Test | Location | Verifies |
|---|---|---|
| `test_multi_ac2_legacy_still_plans` | `tests/scenario/test_multi_project.py` | |
| `test_multi_ac2_converted_on_first_write` | same | |

### AC3 — Plan and apply across projects
**Given** two projects in the file, one new, **then** `plan` lists both projects with their clusters, `apply` creates the new project and its clusters, and a re-run makes zero writes. `--target cluster/PROJECT/NAME` limits to one cluster when the name repeats.

| Test | Location | Verifies |
|---|---|---|
| `test_multi_ac3_plan_apply_two_projects` | `tests/scenario/test_multi_project.py` | |
| `test_multi_ac3_target_qualified_cluster` | same | |

### AC4 — project create adds to the file
**Given** capella.yaml describing `demo`, **when** `capellactl project create non-prod` runs, **then** the project is created in Capella and appended to the file; `demo` and its clusters are unchanged.

| Test | Location | Verifies |
|---|---|---|
| `test_multi_ac4_project_create_appends` | `tests/scenario/test_multi_project.py` | |

### AC5 — Import discovers every project and merges
**Given** an organization with three projects, **then** `import` writes all three; **given** a file that already has one of them, **then** only the missing ones are added and the existing one is left unchanged; `--project` limits the import. A plan straight after reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_multi_ac5_import_all_projects` | `tests/scenario/test_multi_project.py` | |
| `test_multi_ac5_import_merges_missing` | same | |

### AC6 — Sync refreshes every project
**Given** changes in two projects made in the Capella UI, **then** `sync` shows and applies both; `sync --project NAME` refreshes only that one.

| Test | Location | Verifies |
|---|---|---|
| `test_multi_ac6_sync_all_projects` | `tests/scenario/test_multi_project.py` | |

### AC7 — Cluster commands choose the right project
**Given** two projects in the file, **then** `cluster create NAME` asks which project (or needs `--project` in scripts) and writes the cluster under it; **given** the same cluster name in two projects, **then** `cluster scale/update/get NAME` exits 3 asking for `--project`, and works with it.

| Test | Location | Verifies |
|---|---|---|
| `test_multi_ac7_cluster_create_project_choice` | `tests/scenario/test_multi_project.py` | |
| `test_multi_ac7_same_cluster_name_needs_project` | same | |

### AC8 — project list shows what is in the file
**Given** two of three projects in capella.yaml, **then** `project list` shows `IN FILE` as `yes` for those two.

| Test | Location | Verifies |
|---|---|---|
| `test_multi_ac8_project_list_in_file` | `tests/scenario/test_multi_project.py` | |

## Out of scope
- Several organizations in one file.

## Open questions
- None.

## Implementation notes (as built)
- Revised by CAP-054 (2026-10-23): `import` is now an alias of `sync`, so with an existing file it refreshes the projects already there as well as adding the missing ones, and rewrites the file (hand-written comments are not kept; the file is tool-owned).
- Every reader of the file goes through `project_entries()` (`capellactl/config/loader.py`), which returns each project with the YAML paths of the project and of its clusters, so error messages and line numbers point at the real place in either form.
- The JSON schema moved the cluster definition to `$defs.cluster`, shared by `projects[].clusters` and the single-project `clusters`; `oneOf` rejects a file with both forms. `help config` shows the `projects.…` paths and still accepts `clusters.…` and `project.…`.
- Cluster names and networks only need to be unique within a project (Capella's own rule); project names must be unique in the file.
- Targets accept `cluster/PROJECT/NAME`. Cluster commands use the project-qualified target internally, so a repeated name never touches the wrong project; `cluster get/apply/scale/update` find the project themselves unless the name repeats.
- `cluster list` lists the clusters of every project in the organization, with a PROJECT column (JSON items carry `projectId` and `projectName`); `--project NAME` narrows it to one project. It never asks for `--project`; commands that change one cluster still do when the name is ambiguous.
- `import` appends missing projects through the comment-preserving editor, so notes in the file survive. Behaviour that changed: `import` no longer asks which project (it takes all), and `project create` adds to the existing file instead of refusing (CAP-039 AC4 and CAP-036 AC8 revised).
- `sync` compares both files in the `projects:` form, so converting an older single-project file never shows as a difference by itself; projects in the file that no longer exist in Capella are kept, with a warning.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_multi_ac1_validate_and_paths` (tests/unit/config/test_multi_project.py)<br>`test_multi_ac1_name_rules` (tests/unit/config/test_multi_project.py) |
| AC2 | `test_multi_ac2_legacy_still_plans` (tests/scenario/test_multi_project.py)<br>`test_multi_ac2_converted_on_first_write` (tests/scenario/test_multi_project.py) |
| AC3 | `test_multi_ac3_plan_apply_two_projects` (tests/scenario/test_multi_project.py)<br>`test_multi_ac3_target_qualified_cluster` (tests/scenario/test_multi_project.py) |
| AC4 | `test_multi_ac4_project_create_appends` (tests/scenario/test_multi_project.py) |
| AC5 | `test_multi_ac5_import_all_projects` (tests/scenario/test_multi_project.py)<br>`test_multi_ac5_import_merges_missing` (tests/scenario/test_multi_project.py) |
| AC6 | `test_multi_ac6_sync_all_projects` (tests/scenario/test_multi_project.py) |
| AC7 | `test_multi_ac7_cluster_create_project_choice` (tests/scenario/test_multi_project.py)<br>`test_multi_ac7_same_cluster_name_needs_project` (tests/scenario/test_multi_project.py)<br>`test_multi_ac7_cluster_list_every_project` (tests/scenario/test_multi_project.py) |
| AC8 | `test_multi_ac8_project_list_in_file` (tests/scenario/test_multi_project.py) |
