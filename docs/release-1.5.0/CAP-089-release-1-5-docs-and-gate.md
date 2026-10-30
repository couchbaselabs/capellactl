# CAP-089 — 1.5.0 guides, integration suite & release gate

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E17 Release 1.5 | P0 | 5 | CAP-032, CAP-033 | Not started |

## User story
As a **maintainer**, I want the 1.5.0 features covered by the nightly integration suite and by customer guides, so
that 1.5.0 ships with the same confidence and documentation as 1.0.0.

## Context & discovery
- CAP-032 runs the nightly suite against a sandbox organization and gates releases; CAP-033 owns the guides and the
  runbook. Both cover 1.0.0 features only.
- Several 1.5.0 areas need cloud-side resources (peering, private endpoints, CMEK) or organization-owner keys (users,
  API keys, organization settings). The sandbox must provide them or the suite must skip them with a reason.

## Design
- **Integration suite** (`tests/integration/`): one scenario per 1.5.0 area with the CAP-032 rules (unique
  `capellactl-ci-*` names, zero-writes re-run, janitor clean-up). Areas that need customer cloud resources run the
  capellactl side only (enable, list, command) and skip acceptance with `pytest.skip("needs a cloud-side endpoint")`.
- **Guides**: `docs/networking.md` (peering, private endpoints, Data API endpoints), `docs/security.md` (database
  roles, audit logging, CMEK, API keys, users), `docs/operational-insights.md`, and new sections in
  `docs/getting-started.md` (indexes, sample bucket) and `docs/runbook.md` (replication pause/resume, key rotation,
  audit export). Every command in them is parsed in CI, as for 1.0.0.
- **Help**: `help topics` lists the new topics (`networking`, `security`, `insights`, `replication`, `indexes`).
- **Examples**: `docs/release-1.5.0/examples/` with one capella.yaml per area, validated in CI (as
  `tests/unit/docs/test_examples.py` does for 1.0.0).
- **CI**: `scripts/check-ac-coverage.py --docs docs/release-1.5.0` and the 1.5.0 story-index check run in `ci.yml`.

## Acceptance criteria & tests

### AC1 — Nightly suite covers 1.5.0
**Given** the nightly job, **then** every 1.5.0 story with a resource has a scenario that creates, re-runs with zero
writes, and deletes it; skipped scenarios print their reason.

| Test | Location | Verifies |
|---|---|---|
| `test_release15_ac1_every_area_has_a_scenario` | `tests/unit/scripts/test_release15_gate.py` | Story → scenario map |

### AC2 — Guides run
**Given** the new guides, **then** their commands are parsed and run against the fake in CI, as CAP-033 AC5 does.

| Test | Location | Verifies |
|---|---|---|
| `test_release15_ac2_guides_run_against_fake` | `tests/scenario/test_release15_guides.py` | |

### AC3 — Examples validate
**Given** `docs/release-1.5.0/examples/*.yaml`, **then** `capellactl validate` passes on each.

| Test | Location | Verifies |
|---|---|---|
| `test_release15_ac3_examples_validate` | `tests/unit/docs/test_examples_15.py` | |

### AC4 — Help topics
**Given** `help topics`, **then** the five new topics are listed and each prints without error.

| Test | Location | Verifies |
|---|---|---|
| `test_release15_ac4_help_topics` | `tests/scenario/test_release15_guides.py` | |

### AC5 — CI checks the release
**Given** a stale `docs/release-1.5.0/README.md` or an Implemented 1.5.0 story with an untested AC, **then** CI fails.

| Test | Location | Verifies |
|---|---|---|
| `test_release15_ac5_ci_checks_release` | `tests/unit/scripts/test_release15_gate.py` | Reads `.github/workflows/ci.yml` |

## Out of scope
- App Services (2.0.0).

## Open questions
- Can the sandbox organization provide an AWS account for peering and private-endpoint acceptance in the nightly run?
