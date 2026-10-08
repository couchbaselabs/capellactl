# CAP-006 — Apply executor, confirmation, output & exit codes

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P0 | 5 | CAP-005 | Implemented |

## User story
As an **operator**, I want `apply` to show the plan, ask before changing anything, apply changes in the right order, stop cleanly on failure and resume on re-run, so that I can trust it in production and in CI.

## Context & discovery
- Re-runs must be safe after any partial failure; because the tool is stateless, "resume" simply means re-planning and finding completed actions as `=`.
- `BLOCKED` anywhere must prevent a half-applied environment.

## Implementation details

| Module | Responsibility |
|---|---|
| `engine/executor.py` | Runs `Plan.actions` in graph order; per action: `reconciler.apply()` then `reconciler.wait()`; stops at first failure; returns `ApplyResult` |
| `cli/env.py` | `apply` command: plan → render → confirm → execute → summary |
| `output/render.py` | Progress lines `→ creating bucket nova-dev-01/orders … done (1.2s)`; summary table |

Confirmation prompt: `Apply 3 changes to project nova-dev? [y/N]`. Destructive actions (`-`, `±`, scale-in) are listed again under `Destructive changes:` above the prompt.

## Acceptance criteria & tests

### AC1 — No changes
**Given** Capella already matches the file, **when** `apply` runs, **then** it prints `No changes. Capella matches capella.yaml.`, does not prompt, makes zero writes and exits 0.

| Test | Location | Verifies |
|---|---|---|
| `test_apply_ac1_no_changes_no_prompt` | `tests/scenario/test_apply.py` | `fake.writes() == []` |

### AC2 — Confirmation
**Given** changes and an interactive terminal, **then** the plan is shown and the prompt appears; answering `n` exits 0 with `Apply cancelled` and zero writes; `--auto-approve` skips the prompt. **Given** a non-interactive stdin without `--auto-approve`, **then** exit 1 with `refusing to apply without --auto-approve in a non-interactive session`.

| Test | Location | Verifies |
|---|---|---|
| `test_apply_ac2_decline_makes_no_writes` | `tests/scenario/test_apply.py` | |
| `test_apply_ac2_auto_approve` | same | |
| `test_apply_ac2_non_interactive_requires_flag` | same | |

### AC3 — Dependency order
**Given** a plan creating project, cluster, CIDR, bucket, scope, collection and credential, **then** writes occur in that order, and the credential `POST` happens after its referenced collection exists.

| Test | Location | Verifies |
|---|---|---|
| `test_apply_ac3_write_order` | `tests/scenario/test_apply.py` | Order of `fake.writes()` |

### AC4 — Blocked stops everything
**Given** a plan with one `BLOCKED` action and two valid ones, **then** `apply` makes zero writes, prints the blocked reason and exits 4. **Given** `--target` excluding the blocked resource, **then** the other actions run.

| Test | Location | Verifies |
|---|---|---|
| `test_apply_ac4_blocked_prevents_any_write` | `tests/scenario/test_apply.py` | |
| `test_apply_ac4_target_excludes_blocked` | same | |

### AC5 — Stop on first failure, resume on re-run
**Given** the bucket `POST` fails with `422`, **then** later actions are reported `skipped`, the summary lists completed actions, exit 1. **When** the error is fixed and `apply` re-runs, **then** completed actions show `=` and only the remaining actions are executed; no resource is created twice.

| Test | Location | Verifies |
|---|---|---|
| `test_apply_ac5_failure_skips_rest` | `tests/scenario/test_apply.py` | |
| `test_apply_ac5_rerun_resumes_without_duplicates` | same | Count of POSTs per path == 1 |

### AC6 — 409 and 412 recovery
**Given** a create returns `409` code 1010, **then** the executor re-observes, finds the resource, and continues (no error). **Given** an update returns `412` once, **then** it re-reads, re-plans that resource and retries once; a second `412` exits 1 with `resource changed concurrently; re-run plan`.

| Test | Location | Verifies |
|---|---|---|
| `test_apply_ac6_create_conflict_adopts_existing` | `tests/scenario/test_apply.py` | |
| `test_apply_ac6_412_replans_once` | same | |
| `test_apply_ac6_double_412_fails` | same | |

### AC7 — JSON result
**Given** `apply -o json --auto-approve`, **then** the output contains `plan` and `result` per [00-architecture.md §11](00-architecture.md#11-output) and validates against `tests/schemas/apply.schema.json`.

| Test | Location | Verifies |
|---|---|---|
| `test_apply_ac7_json_schema` | `tests/scenario/test_apply.py` | |

### AC8 — Interrupt
**Given** Ctrl-C during an action, **then** the in-flight request finishes or is abandoned, the summary is printed and exit is 130.

| Test | Location | Verifies |
|---|---|---|
| `test_apply_ac8_keyboard_interrupt_exit_130` | `tests/scenario/test_apply.py` | |

## Out of scope
- Parallel execution of independent actions (sequential in 1.0.0 for predictable ordering and rate-limit friendliness).

## Open questions
- None.

## Implementation notes (as built)
- Apply stops at the first failure and lists what completed; a re-run resumes. Durations use the run clock, so they are real in production and deterministic in tests.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_apply_ac1_no_changes_no_prompt` (tests/scenario/test_apply.py) |
| AC2 | `test_apply_ac2_decline_makes_no_writes` (tests/scenario/test_apply.py)<br>`test_apply_ac2_auto_approve` (tests/scenario/test_apply.py)<br>`test_apply_ac2_non_interactive_requires_flag` (tests/scenario/test_apply.py) |
| AC3 | `test_apply_ac3_write_order` (tests/scenario/test_apply.py) |
| AC4 | `test_apply_ac4_blocked_prevents_any_write` (tests/scenario/test_apply.py)<br>`test_apply_ac4_target_excludes_blocked` (tests/scenario/test_apply.py) |
| AC5 | `test_apply_ac5_failure_skips_rest` (tests/scenario/test_apply.py)<br>`test_apply_ac5_rerun_resumes_without_duplicates` (tests/scenario/test_apply.py) |
| AC6 | `test_apply_ac6_create_conflict_adopts_existing` (tests/scenario/test_apply.py)<br>`test_apply_ac6_412_replans_once` (tests/scenario/test_apply.py)<br>`test_apply_ac6_double_412_fails` (tests/scenario/test_apply.py)<br>`test_apply_ac6_ambiguous_post_adopts_created` (tests/scenario/test_apply.py) |
| AC7 | `test_apply_ac7_json_schema` (tests/scenario/test_apply.py) |
| AC8 | `test_apply_ac8_keyboard_interrupt_exit_130` (tests/scenario/test_apply.py) |
