# CAP-047 — configure and import check an existing capella.yaml against the key's organization

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P1 | 3 | CAP-036, CAP-037 | Implemented |

## User story
As a **platform engineer** switching API keys or organizations, I want `capellactl configure` to tell me when the capella.yaml in my directory belongs to a different organization or names projects that do not exist, and `capellactl import` to refuse to mix two organizations in one file, so that I find out right after saving the key instead of from a confusing `project … not found` on a later command.

## Context & discovery
- `configure` (CAP-037) hands off to `import` (CAP-036) only when there is no capella.yaml. When one exists it prints `capella.yaml already exists; to refresh it from Capella: capellactl import --force` and never checks the file. A user saved a key for org *AA-Pricing* while `./capella.yaml` was for org *Couchbase-Field-POC* with project `free-proj`. `configure` succeeded, and `cluster get` then failed with `project free-proj not found`.
- `configure` must not rewrite capella.yaml on its own. The file is the user's desired state, is edited by hand and may be in git. `configure` only warns, and rewrites the file only after an explicit yes, keeping a `.bak`.
- `import` without `--force` adds missing projects to an existing capellactl file. It does not compare organizations, so it can write projects of org B into a file whose `organizationId` is org A.
- `organizationId` in the file may be a literal or a `${VAR}` reference. A reference that cannot be resolved means the org comes from the profile (CAP-037 precedence), so there is nothing to compare.
- Endpoints: `GET /v4/organizations/{organizationId}/projects` (read-only), already used by `import`.

## Implementation details
- After the profile is saved, `configure` reads the config file (`state.config_path()`) without loading secrets. It resolves `organizationId` and compares it with the chosen organization.
  - Different org: print the mismatch and the two ways forward (re-import with a backup, or a separate profile for the other org). When interactive, ask `Back up capella.yaml and re-import it for ORG? [y/N]`.
  - Same org: list the projects and warn about each declared project that Capella does not have.
- `--import` keeps its current meaning: it rewrites an existing file and keeps a `.bak`. `--no-import` still runs the checks but never prompts.
- `import` (no `--force`, no `--stdout`) into a capellactl file with a different resolved `organizationId` exits 3 and writes nothing.

## Acceptance criteria & tests

### AC1 — Organization mismatch is reported
**Given** `./capella.yaml` with `organizationId: org-other` and a key for `Nova Corp (org-1)`, **when** `configure` runs non-interactively, **then** the profile is saved, the output says `capella.yaml is for organization org-other, but this key is for Nova Corp (org-1)` and shows `capellactl import --force` and `capellactl configure --profile NAME`, the file is unchanged, the exit code is 0 and no `POST`/`PUT`/`DELETE` is sent.

| Test | Location | Verifies |
|---|---|---|
| `test_configure_check_ac1_org_mismatch_reported` | `tests/scenario/test_configure_check.py` | |

### AC2 — Interactive re-import with a backup
**Given** AC1 in an interactive terminal, **when** the user answers `y`, **then** the old file is kept as `capella.yaml.bak` and the new capella.yaml has `organizationId: org-1` and the org's projects. **When** the user answers `n` or presses Enter, the file is unchanged.

| Test | Location | Verifies |
|---|---|---|
| `test_configure_check_ac2_reimport_on_yes` | `tests/scenario/test_configure_check.py` | |
| `test_configure_check_ac2_default_keeps_file` | `tests/scenario/test_configure_check.py` | |

### AC3 — Projects missing from the organization
**Given** `./capella.yaml` for org-1 declaring projects `nova-dev` and `free-proj`, and Capella has only `nova-dev`, **then** `configure` prints `capella.yaml declares project free-proj, which is not in organization Nova Corp (projects: nova-dev)` and exits 0.

| Test | Location | Verifies |
|---|---|---|
| `test_configure_check_ac3_missing_project_reported` | `tests/scenario/test_configure_check.py` | |

### AC4 — Matching file: no warning, no writes
**Given** `./capella.yaml` for org-1 (literal, or `${CAPELLA_ORG_ID}` resolved from the environment) whose projects all exist, **then** `configure` prints only the existing `already exists` line and makes zero `POST`/`PUT`/`DELETE` calls. An `organizationId` reference that cannot be resolved gives no mismatch warning.

| Test | Location | Verifies |
|---|---|---|
| `test_configure_check_ac4_matching_file_quiet` | `tests/scenario/test_configure_check.py` | |
| `test_configure_check_ac4_unresolved_org_ref_quiet` | `tests/scenario/test_configure_check.py` | |

### AC5 — import refuses to mix organizations
**Given** `./capella.yaml` for `org-other`, **when** `capellactl import` runs for org-1 without `--force`, **then** it exits 3 with `capella.yaml is for organization org-other, not org-1` and names `--force` (backup kept) and `--file PATH`, and the file is unchanged. With `--force`, the file is rewritten for org-1 and `.bak` is kept. `--stdout` is unaffected.

| Test | Location | Verifies |
|---|---|---|
| `test_configure_check_ac5_import_refuses_other_org` | `tests/scenario/test_configure_check.py` | |

## Out of scope
- Checking clusters, buckets or credentials declared in the file (use `plan` or `drift`).
- Rewriting the file without the user saying yes.

## Open questions
- None.

## Implementation notes (as built)
- `config/loader.py` adds `declared_org_id(path, env)`. It reads `organizationId` without loading or validating the rest of the file, and resolves `${VAR}` from the environment. A `${file:…}` reference or an unset variable returns `None`, which means "the profile decides", so nothing is compared.
- `cli/configure.py`: `_offer_import` calls `_check_existing` whenever the config file exists and `--import` was not given. A mismatch prints the warning and both ways forward. In an interactive terminal (not `--no-import`, not `--api-key-stdin`) it asks `Back up capella.yaml and re-import it for ORG? [y/N]`, and on yes calls `run_import(force=True)`, which keeps the `.bak`. With a matching org it prints the existing `already exists` hint, then compares declared project names with `GET …/projects`. An API error during that check is ignored because the profile is already saved.
- `cli/env.py` `run_import`: before merging into an existing capellactl file, a different resolved `organizationId` exits 3 and writes nothing. `--force` and `--stdout` skip that path, as before.
- README: step 1 notes that an existing `capella.yaml` is never rewritten without asking, and *When something goes wrong* explains `project NAME not found`.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_configure_check_ac1_org_mismatch_reported` (tests/scenario/test_configure_check.py) |
| AC2 | `test_configure_check_ac2_reimport_on_yes`, `test_configure_check_ac2_default_keeps_file` |
| AC3 | `test_configure_check_ac3_missing_project_reported` |
| AC4 | `test_configure_check_ac4_matching_file_quiet`, `test_configure_check_ac4_unresolved_org_ref_quiet` |
| AC5 | `test_configure_check_ac5_import_refuses_other_org` |
