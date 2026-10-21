# CAP-032 — Nightly integration suite & release gate

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P0 | 5 | CAP-030 | In progress |

## User story
As a **maintainer**, I want an automated run against a real Capella sandbox every night, so that idempotency, scaling and hibernation keep working as the API evolves.

## Context & discovery
- The fake (CAP-004) proves logic; only a real run proves API compatibility.
- Cost control: smallest AWS multi-node layout needed for scale tests; single-node for the rest.

## Implementation details
- `tests/integration/` with `@pytest.mark.integration`, run by a scheduled CI job using `CAPELLA_SANDBOX_API_KEY` / `CAPELLA_SANDBOX_ORG_ID` from the CI secret store. (Not the plain `CAPELLA_API_KEY`: `tests/conftest.py` clears it, so a developer's own key never reaches the suite.)
- Each run uses unique project names `capellactl-ci-<run-id>-<purpose>`; a teardown that always runs turns deletion protection off and deletes each project with everything in it.
- A weekly janitor job deletes `capellactl-ci-*` projects older than 24 hours.
- The same suite runs against the fake (CAP-004) on every push, so a broken integration test is caught before the night.

## Acceptance criteria & tests

### AC1 — Full lifecycle with zero-write re-run
**Given** the sandbox, **then** the job runs `apply` → `apply` (asserts zero writes via request logging) → edit (bucket memory, CIDR comment, schedule) → `apply` → `destroy`, and all steps pass.

| Test | Location | Verifies |
|---|---|---|
| `test_integration_ac1_lifecycle` | `tests/integration/test_lifecycle.py` | |
| `test_integration_ac1_zero_writes_read_from_the_request_log` | `tests/unit/test_integration_suite.py` | Writes are counted from the `--log-level debug` request lines |
| `test_integration_nightly_workflow`, `test_integration_rehearsed_on_every_push` | `tests/unit/test_integration_suite.py` | `nightly.yml`; the fake rehearsal in `ci.yml` and `make check` |

### AC2 — Scaling and hibernation on real clusters
**Given** a 3-node cluster, **then** scale out to 4, scale in to 3 (guards pass), power off, power on, create/pause/resume/delete a schedule — each step reaching its expected state.

| Test | Location | Verifies |
|---|---|---|
| `test_integration_ac2_scaling` | `tests/integration/test_scaling.py` | 3 → 4 → 3, then a re-run with no writes |
| `test_integration_ac2_power`, `test_integration_ac2_schedule` | `tests/integration/test_power.py`, `test_schedule.py` | off, off again, on; set, re-run, update, pause, resume, delete |

### AC3 — Always cleans up
**Given** a failure at any step, **then** teardown still runs and the job reports both the failure and the teardown result; the janitor finds no leftovers older than 24 h.

| Test | Location | Verifies |
|---|---|---|
| `test_integration_ac3_teardown_on_failure`, `…_failed_teardown_fails_a_passing_test`, `…_both_failures_reported` | `tests/unit/test_integration_suite.py` | Injected failures, against the fake on every push |
| `test_janitor_deletes_only_old_ci_projects`, `test_janitor_reports_leftovers_and_clean_runs` | `tests/unit/scripts/test_ci_janitor.py` | |

### AC4 — Secrets masked in CI logs
**Given** the job logs, **then** the canary check from CAP-008 runs over the captured log artefact.

| Test | Location | Verifies |
|---|---|---|
| `test_integration_ac4_logs_have_no_secrets` | `tests/integration/test_redaction_ci.py` | |
| `test_scan_ac4_*` | `tests/unit/scripts/test_scan_log_secrets.py` | The scan over the uploaded log, in `nightly.yml` |

### AC5 — Release gate
**Given** a release candidate, **then** release is blocked unless the nightly job was green on three consecutive nights on the candidate commit's branch, the newest of those runs on the candidate commit itself.

| Test | Location | Verifies |
|---|---|---|
| `test_gate_ac5_*` | `tests/unit/scripts/test_release_gate.py` | The rule, and that `release.yml` runs `scripts/release-gate.py` |

## Out of scope
- Performance benchmarks.

## Open questions
- Which sandbox organization and budget will host the nightly runs? **Still open, and it blocks the first real run.**
- ~~A project per run, or a standing sandbox project and cluster?~~ Answered (2026-10-20): a project per run, as proposed.

## Implementation notes (as built)
- **Still open:** the first real run. Create a sandbox organization and an API key for it (Project Owner role
  or higher), add the repository secrets `CAPELLA_SANDBOX_API_KEY` and `CAPELLA_SANDBOX_ORG_ID`, run Actions →
  nightly → Run workflow (job: integration), and check the teardown summary and the uploaded `integration-log`.
  Then run the janitor job once. Record both runs here and set the story to Implemented. The release gate
  (AC5) blocks a `v*` tag until three scheduled runs in a row have passed.
- `tests/integration/harness.py`: `Target` runs every command with `--log-level debug`, appends the output to the
  run log (`CAPELLACTL_IT_LOG`) and reads the request lines back (`Result.writes`: zero writes means no
  POST/PUT/PATCH/DELETE line). `Target.cleanup(project)` is the teardown: it records the test's failure and the
  teardown result in the report (`CAPELLACTL_IT_REPORT`, and a section at the end of the pytest output).
- Target: `CAPELLACTL_IT_TARGET=sandbox` (the nightly job, `make test-integration`) or `fake` (`ci.yml`,
  `make test-integration-fake`, part of `make check`). Unset: sandbox when its two variables are set, otherwise
  skipped.
- Projects per run: `…-life` (AC1: one single-node cluster with protection, schedule, CIDR, bucket, scope,
  collection and a generated-password credential, built and destroyed by the test) and `…-shared` (one 3-node
  AWS cluster and a bucket, created once per run; the AC2 tests and the per-story integration tests of CAP-014,
  -016, -019, -020, -023, -025, -027 and -049 work in it). Schedules in the suite are always on
  (`00:00-24:00`), so Capella never turns a cluster off mid-run.
- The existing integration tests no longer need `CAPELLA_SANDBOX_PROJECT`, `_CLUSTER` or `_BUCKET`. The SDK
  connection test (CAP-027 AC8) needs `CAPELLA_SANDBOX_CLIENT_CIDR`; the nightly job sets it to the runner's
  public address, which is allowed on the shared cluster.
- `scripts/ci-janitor.py` (also `make janitor`): deletes `capellactl-ci-*` projects older than 24 hours
  (protection off, clusters deleted with their snapshots and waited for, then the project). The suite's teardown
  uses the same code. With `--fail-on-leftovers` (the weekly job) it fails when it found anything, so a leak is
  noticed. A project whose creation time can't be read is kept: it may belong to a run in progress.
- `scripts/scan-log-secrets.py`: the CAP-008 canary check over files: the API key, the passwords tests set and
  every generated password saved under the run's `--basetemp` (also JSON-escaped and URL-encoded). It prints only
  where a secret was found, never the value, and exits 2 when there is nothing to check for. The uploaded
  artifact holds the log and the report, never the temporary directory with the saved passwords.
- `scripts/release-gate.py` (AC5): the last three completed *scheduled* runs of `nightly.yml` on `main` succeeded,
  on three consecutive UTC dates, and the newest ran on the release commit. Manual runs don't count. On a tag
  push it blocks; on the release workflow's manual dry run it only reports.
- `.github/workflows/nightly.yml`: integration at 07:00 UTC every night, janitor on Sundays, both also by hand;
  one run at a time against the sandbox, never cancelled mid-teardown; 5-hour timeout.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_integration_ac1_lifecycle` (sandbox; fake on every push), `test_integration_ac1_zero_writes_read_from_the_request_log`, `test_integration_nightly_workflow`, `test_integration_rehearsed_on_every_push` |
| AC2 | `test_integration_ac2_scaling`, `test_integration_ac2_power`, `test_integration_ac2_schedule` |
| AC3 | `test_integration_ac3_teardown_on_failure`, `test_integration_ac3_failed_teardown_fails_a_passing_test`, `test_integration_ac3_both_failures_reported`, `test_janitor_*` |
| AC4 | `test_integration_ac4_logs_have_no_secrets`, `test_scan_ac4_*` |
| AC5 | `test_gate_ac5_*` |
