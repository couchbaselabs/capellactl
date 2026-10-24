# CAP-054 — One command to bring capella.yaml in line with Capella: `sync` covers the whole organization

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P1 | 5 | CAP-036, CAP-038, CAP-040 | Implemented |

## User story
As an **operator**, I want one command that makes capella.yaml describe everything my organization has in Capella, including projects and clusters made in the Capella UI and clusters that are turned off right now, so that I never have to know whether to run `import` or `sync`, and never see "in sync" while clusters are missing from the file.

## Context & discovery
- Two commands do nearly the same thing today:
  - `import` (CAP-036, CAP-040) reads **every project** in the organization by default; with an existing file it **adds the missing projects** and leaves the others alone (`--force` rewrites them).
  - `sync` (CAP-038) refreshes **only the projects already in capella.yaml**, and ignores the rest without saying so ([sync.py](../../capellactl/cli/sync.py)).
  - Both read through the same `build_document`.
- Found 2026-10-23 with a real organization: capella.yaml held project `sandbox` (no clusters). `cluster list` showed 5 clusters in project `non-prod`, which covers every project. `sync --dry-run` answered `capella.yaml is already in sync with Capella.` and exited 0, which was true only for the file's own projects.
- The product says one file describes the organization (`help config`: "One file describes your organization: every project"; CAP-040). So the default for `sync` should be the whole organization, like `import`, not just the file's projects.
- Turned-off clusters: buckets and credentials cannot be read while a cluster is `turnedOff`/`turningOff`/`turningOn`. Neither command waits: the cluster's size, groups, schedule and allowed CIDRs are recorded, the rest is noted, and the next run once it is on fills it in. CAP-038 AC14 (2026-10-23) makes sure a sync while it is off keeps what the file already had. This story makes that visible in the summary.

## Design

### One command
```
capellactl sync [--project NAME …] [--project-id ID …] [--cluster NAME …] [--cluster-id ID …]
                [--skip-project NAME …] [--dry-run] [--stdout] [--full] [--force]
```

| Situation | What `sync` does |
|---|---|
| No capella.yaml | Creates it from every project in the organization (what `import` does today) |
| capella.yaml exists | Refreshes every project in it **and adds the organization's projects that are not in it** |
| `--project`/`--project-id` | This run covers only those projects (added if new, refreshed if present); others are left as they are |
| `--cluster`/`--cluster-id` | As today: refreshes only those clusters |
| `--skip-project NAME` | Leaves that project out now and on every later sync; recorded in capella.yaml as `skipProjects: [NAME]` (written by the tool, like everything else in the file). `sync --project NAME` brings it back and removes it from the list |
| `--stdout` | Prints the YAML instead of writing (from `import`) |
| `--force` | Needed in scripts only to replace a file that is not a capellactl file (from `import`) |

- `import` stays as a **hidden alias** of `sync` for one release. It prints `note: 'import' is now 'sync'` and takes its old options (`--file` → `--config`). This follows the same pattern used to retire `project apply`/`cluster apply` (architecture §5).
- No new API calls: `GET …/projects`, `GET …/clusters` and the per-cluster reads that `import` and `sync` already make.

### Turned-off and unreadable clusters
- **Nothing waits**: a powered-off cluster is recorded at once with what Capella returns (size, service groups, schedule, allowed CIDRs).
- **First time** a cluster is seen while off: the file notes `not imported: buckets and database credentials …` (as today).
- **Already recorded**: its buckets and credentials are kept from the file (CAP-038 AC14).
- **Next sync after it is on**: everything is read and the notes disappear. This works with no flag, so a scheduled `sync` picks clusters up as they wake.

### Output
```
added project non-prod (5 clusters)
refreshed project sandbox (0 clusters)
3 clusters are turned off: RMPRCCBETST, RMPRCCBWTST, ct-n-zweus-mktfareevl-stg
  buckets and credentials: not read yet (first sync) — sync again when they are on
capella.yaml updated from Capella (previous version kept as capella.yaml.bak).
```
When nothing changed: `capella.yaml is in sync with Capella: 2 projects, 5 clusters (3 turned off; see above)`. The message names what it covered, so "in sync" is never claimed for projects it did not look at. With `--project`, it says `in sync for sandbox (other projects not checked)`.

### Where the code goes
- `cli/sync.py`: project selection (organization projects minus `skipProjects`, or the `--project` list), creating the file when missing, `--stdout`, `--force`, `--skip-project`, and the summary.
- `cli/env.py`: `import` becomes a hidden command that forwards to `sync`.
- `config/schema.json`: top-level `skipProjects` (array of project names), so `make docs` regenerates `docs/reference.md`.
- Docs: `docs/getting-started.md`, `docs/runbook.md`, `README.md` and the help topics use `sync` only.

## Acceptance criteria & tests

### AC1 — Sync adds projects that are not in the file
**Given** capella.yaml with project `sandbox` and a Capella organization that also has `non-prod` with clusters, **when** `capellactl sync` runs, **then** `non-prod` and its clusters are added, `sandbox` is refreshed, the summary says `added project non-prod (N clusters)`, and a second sync reports `in sync … 2 projects`. **Given** `sync --dry-run` before that, **then** the diff shows the added project and the exit code is 2.

| Test | Location | Verifies |
|---|---|---|
| `test_sync_all_ac1_adds_missing_projects` | `tests/scenario/test_sync_all.py` | |
| `test_sync_all_ac1_dry_run_flags_missing_project` | same | Exit 2 |

### AC2 — Sync creates the file when there is none
**Given** no capella.yaml, **then** `sync` writes the same file `import` writes today (same content for the fake organization, by fixture), and `--stdout` prints it without writing.

| Test | Location | Verifies |
|---|---|---|
| `test_sync_all_ac2_creates_file_like_import` | `tests/scenario/test_sync_all.py` | |
| `test_sync_all_ac2_stdout` | same | |

### AC3 — Limiting and skipping projects
**Given** `sync --project sandbox`, **then** only `sandbox` is read and the summary says `other projects not checked`. **Given** `sync --skip-project non-prod`, **then** `non-prod` is removed from the file (if present), `skipProjects: [non-prod]` is recorded, and later syncs neither add it nor report it as missing; `sync --project non-prod` adds it back and removes it from `skipProjects`.

| Test | Location | Verifies |
|---|---|---|
| `test_sync_all_ac3_project_limits_run` | `tests/scenario/test_sync_all.py` | |
| `test_sync_all_ac3_skip_project_remembered` | same | |
| `test_sync_all_ac3_skip_on_first_sync` | same | |

### AC4 — Turned-off clusters do not hold up the run and are picked up later
**Given** three of five clusters turned off, **then** sync makes no wait and no bucket or credential request for them, records their size and service groups, and lists them in the summary. **When** one is turned on and sync runs again, **then** its buckets and credentials are added and it is no longer listed. **Given** a turned-off cluster already recorded with buckets, **then** they are kept (CAP-038 AC14).

| Test | Location | Verifies |
|---|---|---|
| `test_sync_all_ac4_turned_off_not_waited_for` | `tests/scenario/test_sync_all.py` | No bucket/user GETs |
| `test_sync_all_ac4_picked_up_when_on` | same | |

### AC5 — `import` is an alias of `sync`
**Given** `capellactl import` with any of its documented option sets (`--project`, `--cluster`, `--file`, `--stdout`, `--force`, `--full`), **then** it gives the same result as the matching `sync` and prints `note: 'import' is now 'sync'`. `import` no longer appears in `capellactl --help`; `help import` points to `sync`.

| Test | Location | Verifies |
|---|---|---|
| `test_sync_all_ac5_import_alias` | `tests/scenario/test_sync_all.py` | Parametrised |

### AC6 — Read-only and idempotent
**Given** any sync, **then** only `GET` requests are made (CAP-038 AC11). **Given** a second sync with nothing changed in Capella, **then** the file is not rewritten and no `.bak` is made.

| Test | Location | Verifies |
|---|---|---|
| `test_sync_all_ac6_only_gets_and_no_rewrite` | `tests/scenario/test_sync_all.py` | |

### AC7 — Docs use one command
**Given** `docs/getting-started.md`, `docs/runbook.md`, `README.md` and the help topics, **then** they use `sync` for both first-time setup and refresh, and the walkthrough test passes.

| Test | Location | Verifies |
|---|---|---|
| `test_sync_all_ac7_docs_use_sync` | `tests/scenario/test_readme_walkthrough.py` | |

## Out of scope
- Writing a cluster's structure to a separate file and cloning from it (export / clone-from-file; a possible CAP-055).
- Organizations other than the profile's.

## Open questions
- Some teams keep one file per project (a profile `configFile` per team). With the organization as the default, their first sync adds every other project. Is `--skip-project` enough, or should a file created with `sync --project NAME` remember that scope and stay limited to it? Proposed: remember the scope (`syncProjects: [NAME]`) if a customer asks; start with `skipProjects`.
- Should `import` be removed in 1.1 or kept as a permanent alias?

## Implementation notes (as built)
- `cli/sync.py::sync_or_create` is the one entry point: a missing file, a file that is not a capellactl file, or `--force` goes to the existing import writer (`cli/env.py::run_import`); a capellactl file goes to `run_sync`. `import` is a hidden command that prints `note: 'import' is now 'sync'` (not with `--stdout`) and calls the same function, keeping its `--file` option. `configure`, `init` and `cluster clone` still call `run_import` directly.
- `run_sync` refreshes the file's projects as before (CAP-038, CAP-048) and then adds every organization project that is neither in the file nor in `skipProjects`. With `--cluster`/`--cluster-id` and no `--project`, new projects are not added (the run is about those clusters).
- `skipProjects` is a new top-level, tool-written key in `config/schema.json` (`x-mutability: tool`), written before `projects:`. `--skip-project NAME` on a first sync creates the file without that project and records it.
- The org check of CAP-047 applies to `sync` as well: a file for another organization is refused unless `--force` (or printed for the key's organization with `--stdout`).
- The summary says what was covered: `added project NAME (N clusters)`, the turned-off clusters (with "kept from capella.yaml" or "not read yet"), and `already in sync with Capella: P projects, C clusters` (`for NAME (other projects not checked)` with `--project`; `skipped: …` when some are).
- Behaviour change: `import` with an existing file used to add missing projects and leave the others as they were (keeping hand-written comments). As an alias of `sync` it now also refreshes the existing projects and rewrites the file like `sync` always has. CAP-040 AC5's test was updated accordingly.
- Messages that pointed to `capellactl import` (missing file, project not in the file, `configure`, `init`, the not-imported notes) now point to `capellactl sync`, and the customer documents use `sync` only.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_sync_all_ac1_adds_missing_projects`, `test_sync_all_ac1_dry_run_flags_missing_project` (tests/scenario/test_sync_all.py) |
| AC2 | `test_sync_all_ac2_creates_file_like_import`, `test_sync_all_ac2_stdout` (tests/scenario/test_sync_all.py) |
| AC3 | `test_sync_all_ac3_project_limits_run`, `test_sync_all_ac3_skip_project_remembered`, `test_sync_all_ac3_skip_on_first_sync` (tests/scenario/test_sync_all.py) |
| AC4 | `test_sync_all_ac4_turned_off_not_waited_for`, `test_sync_all_ac4_picked_up_when_on` (tests/scenario/test_sync_all.py) |
| AC5 | `test_sync_all_ac5_import_alias` (tests/scenario/test_sync_all.py) |
| AC6 | `test_sync_all_ac6_only_gets_and_no_rewrite` (tests/scenario/test_sync_all.py) |
| AC7 | `test_sync_all_ac7_docs_use_sync` (tests/scenario/test_readme_walkthrough.py) |
