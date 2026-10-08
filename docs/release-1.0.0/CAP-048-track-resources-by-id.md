# CAP-048 — Track projects and clusters by id so renames in the Capella UI are not mistaken for new resources

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P0 | 5 | CAP-009, CAP-012, CAP-036, CAP-038 | Implemented |

## User story
As a **platform engineer**, I want `plan` to show a project or cluster renamed in the Capella UI as a rename, and never as a new project and cluster, so that `apply` cannot quietly create a duplicate (and billed) environment, and `sync` can adopt the new name.

## Context & discovery
- A user renamed project `apex-demo` in the Capella UI and ran `plan`. capella.yaml identified the project by name only, so `plan` showed `+ project apex-demo` and `+ cluster apex-demo-01`. `apply` would have created a second project and a second cluster.
- Pinning (`id:`) already works: a pinned project shows `~ project name: "old" → "new"` (CAP-009 AC5), a pinned cluster can be renamed (CAP-012 AC6), and `sync` keeps a pinned project's `id`. But `import` pinned only free-tier clusters and clusters with duplicate names, so files written by `import` or `sync` had no ids.
- A file without ids (hand-written, `init`, or older imports) still needs a safety net.
- Endpoints: `GET …/projects`, `GET …/projects/{projectId}/clusters` (read-only), already used.

## Implementation details
- `import` and `sync` write `id:` for every project and every cluster.
- `plan`: a pinned project or cluster whose name differs in Capella shows `~ … name: "capella" → "file"` with the note `(renamed in Capella? 'capellactl sync' keeps the new name)`.
- `plan`: an unpinned project that is not in Capella by name, while a project that is not in the file contains one of its declared clusters, is **blocked**: `no project named P; project Q has its cluster C, so it was probably renamed in Capella. Run 'capellactl sync' to adopt the new name, or rename it back in Capella`.
- `sync`: an unpinned project not found by name is matched through its declared cluster names (exactly one candidate project) and refreshed with the new name and its `id`.

## Acceptance criteria & tests

### AC1 — import pins ids
**Given** a project with one cluster, **then** `import` writes `id:` for the project and the cluster. `plan` right after reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_track_by_id_ac1_import_pins_ids` | `tests/scenario/test_track_by_id.py` | |

### AC2 — Pinned project renamed in the UI
**Given** an imported file and the project renamed in Capella to `nova-dev-renamed`, **then** `plan` shows `~ project nova-dev` with `name:  "nova-dev-renamed" → "nova-dev"` and the sync note, no `+` lines, and exits 0.

| Test | Location | Verifies |
|---|---|---|
| `test_track_by_id_ac2_pinned_rename_shown_as_rename` | `tests/scenario/test_track_by_id.py` | |

### AC3 — sync adopts the new name
**Given** AC2, **then** `sync` writes `name: nova-dev-renamed` with the same `id`, and `plan --detailed-exitcode` exits 0 with zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_track_by_id_ac3_sync_adopts_new_name` | `tests/scenario/test_track_by_id.py` | |

### AC4 — Unpinned file: create is blocked
**Given** a file without ids and the project renamed in Capella, **then** `plan` shows the project as blocked with `project nova-dev-renamed has its cluster nova-dev-01` and `capellactl sync`, and `apply` exits 4 with zero writes. A genuinely new project (no declared cluster found elsewhere) is still planned as `+ project`.

| Test | Location | Verifies |
|---|---|---|
| `test_track_by_id_ac4_unpinned_rename_blocks_create` | `tests/scenario/test_track_by_id.py` | |
| `test_track_by_id_ac4_new_project_still_created` | `tests/scenario/test_track_by_id.py` | |

### AC5 — sync finds an unpinned renamed project
**Given** AC4, **then** `sync` adopts `nova-dev-renamed`, writes its `id` and the clusters' ids, and `plan --detailed-exitcode` exits 0.

| Test | Location | Verifies |
|---|---|---|
| `test_track_by_id_ac5_sync_adopts_unpinned_rename` | `tests/scenario/test_track_by_id.py` | |

## Out of scope
- Buckets, scopes, collections and credentials: Capella does not allow renaming them.
- Copying a file to another organization: remove the `id:` lines first (a pinned id that is not found is never created, CAP-009 AC5).

## Open questions
- None.

## Implementation notes (as built)
- `importer.build_document` writes `id:` first for every project and every cluster (`export_cluster(pin_id=True)`); `sync` uses the same builder, so it writes them too.
- `cli/env.py` `pin_created_ids()` runs after every apply (the `apply` command and all single commands). It records the id of each project and cluster created, keeping the file's comments. `_record_server_version` re-reads the file, so it no longer overwrites those ids.
- `resources/base.py` `RENAMED_NOTE` is shown on a pinned project or cluster whose `name` differs in Capella.
- `ProjectReconciler._renamed_from` runs only when an unpinned project is missing by name. It lists the clusters of the Capella projects that are not in the file, and blocks the create when one holds a declared cluster. `sync._renamed_project` uses the same test and adopts the project when exactly one candidate matches.
- `engine/planner.py` no longer plans the children of a resource that is blocked before it exists, so a blocked project does not also list `+ cluster … (after project is created)` or count it as an add.
- README: step 1 explains the `id:` lines and how to copy a file to another organization; *When something goes wrong* explains the blocked plan.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_track_by_id_ac1_import_pins_ids` (tests/scenario/test_track_by_id.py); `test_cluster_cli_ac11_create_then_in_sync` shows created clusters are pinned |
| AC2 | `test_track_by_id_ac2_pinned_rename_shown_as_rename` |
| AC3 | `test_track_by_id_ac3_sync_adopts_new_name` |
| AC4 | `test_track_by_id_ac4_unpinned_rename_blocks_create`, `test_track_by_id_ac4_new_project_still_created` |
| AC5 | `test_track_by_id_ac5_sync_adopts_unpinned_rename` |
