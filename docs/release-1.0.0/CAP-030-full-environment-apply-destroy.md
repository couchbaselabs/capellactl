# CAP-030 — Full-environment apply & destroy

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P0 | 5 | CAP-009–CAP-029 (all P0 resource stories) | Implemented |

## User story
As an **operator**, I want to build or tear down a complete environment with one command, so that a new environment takes minutes of my time instead of a runbook of manual steps.

## Context & discovery
- Builds on every resource reconciler and the executor (CAP-006).
- Dependency order: [00-architecture.md §4.2](00-architecture.md#42-dependency-order).

## Implementation details
- `apply` with no `--target` reconciles everything in the file.
- `destroy` builds a delete plan for every resource **declared in the file**, in reverse order: credentials → collections → scopes → buckets → CIDRs → schedule → cluster → project.
- Final summary table: `KIND  NAME  ACTION  STATUS  DURATION`, then `connectionString` per cluster.

## Acceptance criteria & tests

### AC1 — From scratch to ready
**Given** an empty organization and [examples/capella.yaml](examples/capella.yaml), **when** `apply --auto-approve` runs, **then** writes happen in the order project → cluster (wait healthy) → deletion protection → schedule → CIDRs → buckets → scopes → collections → credentials, and the summary lists every resource as `created` plus the `connectionString`.

| Test | Location | Verifies |
|---|---|---|
| `test_env_ac1_full_build_order` | `tests/scenario/test_environment.py` | Write order |
| `test_env_ac1_summary_table` | same | Golden output |

### AC2 — Second run makes zero writes
**Given** AC1 completed, **then** `apply` prints `No changes`, zero writes, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_env_ac2_second_run_zero_writes` | `tests/scenario/test_environment.py` | |

### AC3 — Resume after interruption
**Given** AC1 is interrupted after the buckets are created (simulated failure on the first scope `POST`), **when** `apply` re-runs, **then** only scopes, collections and credentials are created; each resource has exactly one create call across both runs.

| Test | Location | Verifies |
|---|---|---|
| `test_env_ac3_resume_after_failure` | `tests/scenario/test_environment.py` | |

### AC4 — Destroy in reverse order
**Given** the environment from AC1 with deletion protection turned off, **when** `destroy` is confirmed by typing `nova-dev`, **then** deletes happen in reverse order, the cluster delete is waited on, and the project is deleted last.

| Test | Location | Verifies |
|---|---|---|
| `test_env_ac4_destroy_reverse_order` | `tests/scenario/test_environment.py` | |

### AC5 — Destroy is blocked by protection
**Given** `deletionProtection: true` on the cluster, **then** `destroy` exits 4 with the CAP-013 message, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_env_ac5_destroy_blocked_by_protection` | `tests/scenario/test_environment.py` | |

### AC6 — Destroy only what is declared
**Given** the project also contains cluster `someone-else` not in the file, **then** `destroy` deletes the declared cluster but **not** the project, and prints `project nova-dev kept: contains undeclared cluster someone-else`, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_env_ac6_destroy_keeps_project_with_undeclared` | `tests/scenario/test_environment.py` | |

### AC7 — Destroy is idempotent
**Given** the environment is already gone, **then** `destroy` prints `nothing to destroy`, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_env_ac7_destroy_nothing` | `tests/scenario/test_environment.py` | |

## Out of scope
- Multi-project files.

## Open questions
- None.

## Implementation notes (as built)
- `apply` needed no new code for AC1–AC3 beyond the schedule reconciler (CAP-020); the planner now orders actions by kind within each cluster (all buckets, then all scopes, then all collections …), so writes follow the story's order and `destroy` is its exact reverse (`engine/planner.py::_by_kind`, CAP-006 AC3 and CAP-025 AC1 tests updated to that order).
- `capellactl destroy [--discard-snapshots]` (`cli/env.py`): checks deletion protection first (AC5), plans a delete for every declared resource that exists, shows it, and asks for the project name to be typed (`--auto-approve` skips it; without a terminal it is required). Cluster deletes wait until the cluster is gone; snapshot backups are kept unless `--discard-snapshots`.
- The contents of a cluster that is not `healthy` (for example turned off) are left to the cluster delete, which removes them with the cluster.
- capella.yaml keeps describing the environment, so `capellactl apply` builds it again; only the `id:` of each deleted project and cluster is removed (`.bak` kept), because a pinned id that no longer exists stops `apply` (CAP-048). Found by the getting-started walkthrough test, which now runs destroy → apply.
- AC3 uses a `422` on the first scope `POST` (a `5xx` would be retried by the client).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_env_ac1_full_build_order` (tests/scenario/test_environment.py)<br>`test_env_ac1_summary_table` (tests/scenario/test_environment.py) |
| AC2 | `test_env_ac2_second_run_zero_writes` (tests/scenario/test_environment.py) |
| AC3 | `test_env_ac3_resume_after_failure` (tests/scenario/test_environment.py) |
| AC4 | `test_env_ac4_destroy_reverse_order` (tests/scenario/test_environment.py) |
| AC5 | `test_env_ac5_destroy_blocked_by_protection` (tests/scenario/test_environment.py) |
| AC6 | `test_env_ac6_destroy_keeps_project_with_undeclared` (tests/scenario/test_environment.py) |
| AC7 | `test_env_ac7_destroy_nothing` (tests/scenario/test_environment.py) |

