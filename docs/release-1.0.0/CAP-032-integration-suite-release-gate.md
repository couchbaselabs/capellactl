# CAP-032 — Nightly integration suite & release gate

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P0 | 5 | CAP-030 | Not started |

## User story
As a **maintainer**, I want an automated run against a real Capella sandbox every night, so that idempotency, scaling and hibernation keep working as the API evolves.

## Context & discovery
- The fake (CAP-004) proves logic; only a real run proves API compatibility.
- Cost control: smallest AWS multi-node layout needed for scale tests; single-node for the rest.

## Implementation details
- `tests/integration/` with `@pytest.mark.integration`, run by a scheduled CI job using `CAPELLA_API_KEY` / `CAPELLA_ORG_ID` from the CI secret store.
- Each run uses a unique project name `capellactl-ci-<run-id>`; a `finally` teardown runs `destroy --auto-approve` (after turning protection off).
- A weekly janitor job deletes `capellactl-ci-*` projects older than 24 hours.

## Acceptance criteria & tests

### AC1 — Full lifecycle with zero-write re-run
**Given** the sandbox, **then** the job runs `apply` → `apply` (asserts zero writes via request logging) → edit (bucket memory, CIDR comment, schedule) → `apply` → `destroy`, and all steps pass.

| Test | Location | Verifies |
|---|---|---|
| `test_integration_ac1_lifecycle` | `tests/integration/test_lifecycle.py` | |

### AC2 — Scaling and hibernation on real clusters
**Given** a 3-node cluster, **then** scale out to 4, scale in to 3 (guards pass), power off, power on, create/pause/resume/delete a schedule — each step reaching its expected state.

| Test | Location | Verifies |
|---|---|---|
| `test_integration_ac2_scaling` | `tests/integration/test_scaling.py` | |
| `test_integration_ac2_power_and_schedule` | `tests/integration/test_power.py`, `test_schedule.py` | |

### AC3 — Always cleans up
**Given** a failure at any step, **then** teardown still runs and the job reports both the failure and the teardown result; the janitor finds no leftovers older than 24 h.

| Test | Location | Verifies |
|---|---|---|
| `test_integration_ac3_teardown_on_failure` | `tests/integration/conftest.py` | Injected failure |

### AC4 — Secrets masked in CI logs
**Given** the job logs, **then** the canary check from CAP-008 runs over the captured log artefact.

| Test | Location | Verifies |
|---|---|---|
| `test_integration_ac4_logs_have_no_secrets` | `tests/integration/test_redaction_ci.py` | |

### AC5 — Release gate
**Given** a release candidate, **then** release is blocked unless the nightly job was green on three consecutive nights on the candidate commit's branch.

| Test | Location | Verifies |
|---|---|---|
| CI rule `release-gate` | `.github/workflows/release.yml` | |

## Out of scope
- Performance benchmarks.

## Open questions
- Which sandbox organization and budget will host the nightly runs?
