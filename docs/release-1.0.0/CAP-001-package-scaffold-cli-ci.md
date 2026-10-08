# CAP-001 — Python package scaffold, CLI skeleton & CI

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P0 | 3 | — | Implemented |

## User story
As a **platform engineer**, I want to install `capellactl` with one command and get a consistent help screen, so that I can start using it without assembling scripts by hand.

## Context & discovery
- Language and stack decided in [00-architecture.md §2](00-architecture.md#2-technology-decision).
- The customer runs macOS laptops and Linux CI runners; Windows support is needed for one team.
- AC-to-test traceability (§12.2) needs a CI check, which this story provides.

## Implementation details

### Repository layout
As in [00-architecture.md §4](00-architecture.md#4-architecture), plus:

| File | Purpose |
|---|---|
| `pyproject.toml` | hatchling build, `capellactl = capellactl.cli.main:cli` entry point, Python `>=3.10,<3.14` |
| `Makefile` | `lint`, `typecheck`, `test`, `test-integration`, `build`, `image`, `index` |
| `Dockerfile` | `python:3.12-slim`, non-root user, entrypoint `capellactl` |
| `.github/workflows/ci.yml` | matrix: Python 3.10 & 3.13 × ubuntu, macOS, windows |
| `tests/conftest.py` | registers the `story` and `integration` markers |
| `scripts/check-ac-coverage.py` | fails if any `### ACn` of an `Implemented` story has no `@pytest.mark.story("CAP-NNN","ACn")` test; lists gaps of `In progress` stories |
| `cli/exit_codes.py` | exit codes from [00-architecture.md §5.3](00-architecture.md#53-exit-codes) |

### Global options
`--config/-c`, `--output/-o text|json`, `--log-level`, `--auto-approve`, `--no-wait`, `--timeout` are defined once on the root group and passed via the click context object.

## Acceptance criteria & tests

### AC1 — Install and version
**Given** a clean Python 3.10 or 3.13 environment, **when** the wheel is installed with `pipx install`, **then** `capellactl --version` prints `capellactl <version> (Management API v4.0)` and exits 0.

| Test | Location | Verifies |
|---|---|---|
| `test_cli_ac1_version_output` | `tests/unit/cli/test_main.py` | Output text and exit 0 via `CliRunner` |
| CI job `install-smoke` | `.github/workflows/ci.yml` | `pipx install dist/*.whl && capellactl --version` on the OS matrix |

### AC2 — Command tree and help
**Given** the installed tool, **when** `capellactl --help` runs, **then** it lists `help, completion, configure, init, import, sync, validate, plan, apply, destroy, drift, project, cluster, cidr, bucket, scope, collection, credential`, and every group's `--help` contains an `Examples:` section.

| Test | Location | Verifies |
|---|---|---|
| `test_cli_ac2_root_lists_all_groups` | `tests/unit/cli/test_main.py` | Exact group set |
| `test_cli_ac2_every_group_has_examples` | same | Walks the click tree |

### AC3 — Global flags everywhere
**Given** any command, **when** it is invoked with each global flag, **then** the flag is accepted and visible on the context object; an invalid `--output yaml` exits 2 (click usage error) with the allowed values listed.

| Test | Location | Verifies |
|---|---|---|
| `test_cli_ac3_global_flags_reach_context` | `tests/unit/cli/test_main.py` | Parametrised over all commands |
| `test_cli_ac3_invalid_output_format` | same | |

### AC4 — Exit codes defined once
**Given** `cli/exit_codes.py`, **then** it defines exactly the codes 0, 1, 2, 3, 4, 5, 130 and no module uses a numeric literal in `sys.exit` / `ctx.exit`.

| Test | Location | Verifies |
|---|---|---|
| `test_exit_codes_ac4_values` | `tests/unit/cli/test_exit_codes.py` | |
| ruff rule / grep check in `make lint` | `Makefile` | No literal exit codes |

### AC5 — CI pipeline and AC coverage check
**Given** a pull request, **then** CI runs ruff, mypy, unit/contract/scenario tests, builds the wheel and image, and runs `scripts/check-ac-coverage.py`, which fails when an AC of an `Implemented` story has no tagged test, and lists (without failing) untested ACs of `In progress` stories; `--strict` makes those fail too.

| Test | Location | Verifies |
|---|---|---|
| `test_ac_coverage_ac5_detects_missing_test` | `tests/unit/scripts/test_check_ac_coverage.py` | Fixture story with AC3 untagged → non-zero exit naming `CAP-999 AC3` |
| `test_ac_coverage_ac5_passes_when_all_tagged` | same | |

### AC6 — Container image
**Given** the built image, **when** run as `docker run capellactl:<v> --version`, **then** it prints the version, runs as a non-root user, and adds less than 50 MB to the `python:3.12-slim` base image (the base alone is about 150 MB uncompressed, so the tool's own footprint is what is measured).

| Test | Location | Verifies |
|---|---|---|
| CI job `image-smoke` | `.github/workflows/ci.yml` | Version, `id -u` ≠ 0, size |

## Out of scope
- Publishing to PyPI (decided at release time; CAP-033).
- Homebrew formula.

## Open questions
- Will the customer consume the wheel from an internal package index, or only the container image?

## Implementation notes (as built)
- Verified: wheel installs and runs on Python 3.12 (macOS) and on Python 3.10 and 3.13 (Linux containers). Windows is covered by the CI matrix, which has not run yet because the repository has no remote.
- Container image: runs as uid 10001 and adds 42 MB to `python:3.12-slim`. AC6 originally said 'under 150 MB', which no image can meet because the base alone is about 150 MB uncompressed; the AC now measures what the tool adds (< 50 MB).
- AC5: the coverage check fails for `Implemented` stories and lists the open ACs of `In progress` stories, so stories can be marked `In progress` as soon as work starts (INDEX.md rule).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_cli_ac1_version_output` (tests/unit/cli/test_main.py) |
| AC2 | `test_cli_ac2_root_lists_all_groups` (tests/unit/cli/test_main.py)<br>`test_cli_ac2_every_group_has_examples` (tests/unit/cli/test_main.py) |
| AC3 | `test_cli_ac3_global_flags_reach_context` (tests/unit/cli/test_main.py)<br>`test_cli_ac3_invalid_output_format` (tests/unit/cli/test_main.py) |
| AC4 | `test_exit_codes_ac4_values` (tests/unit/cli/test_exit_codes.py)<br>`test_exit_codes_ac4_no_numeric_literals` (tests/unit/cli/test_exit_codes.py) |
| AC5 | `test_ac_coverage_ac5_detects_missing_test` (tests/unit/scripts/test_check_ac_coverage.py)<br>`test_ac_coverage_ac5_in_progress_gaps_listed_not_failed` (tests/unit/scripts/test_check_ac_coverage.py)<br>`test_ac_coverage_ac5_passes_when_all_tagged` (tests/unit/scripts/test_check_ac_coverage.py)<br>`test_ac_coverage_ac5_ignores_not_started` (tests/unit/scripts/test_check_ac_coverage.py) |
| AC6 | `test_image_ac6_dockerfile_non_root_entrypoint` (tests/unit/test_packaging.py)<br>`test_image_ac6_ci_checks_size_and_user` (tests/unit/test_packaging.py) |
