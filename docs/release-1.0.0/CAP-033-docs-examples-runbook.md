# CAP-033 — Examples, runbook & customer documentation

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P0 | 3 | CAP-030 | Implemented |

## User story
As a **customer engineer new to Capella**, I want clear examples and a short runbook, so that I can set up my first environment in under an hour and handle day-2 tasks without help.

## Context & discovery
- The [README](../../README.md) explains what the tool is and how to use it; this story adds the deeper guides and keeps every command in them tested.

## Implementation details

| Document | Content |
|---|---|
| `docs/getting-started.md` | Bootstrap API key in the Capella UI and its roles; install; `configure`; then `init` (new environment) or `import` (existing one); `validate` → `plan` → `apply` |
| `docs/runbook.md` | Scale out / in / up; power off/on; set up, pause, resume a hibernation schedule; add a bucket, collection or app credential; rotate a password; add an office IP; recover from `deploymentFailed`; tear down |
| `docs/reference.md` | Generated from `config/schema.json`: every field, API mapping, default, updatable vs immutable |
| `docs/migrating-from-scale-script.md` | Nova script → `capellactl` mapping (CAP-018 AC7) |
| `docs/terraform.md` | When to prefer the official Couchbase Capella Terraform provider |
| `examples/capella.yaml` | Multi-node AWS reference with schedule |
| `examples/single-node-dev.yaml` | Cheapest developer cluster with weekday schedule |
| `examples/gcp-prod.yaml`, `examples/azure-prod.yaml` | Provider disk settings, deletion protection on, no schedule |

## Acceptance criteria & tests

### AC1 — Every example validates
**Given** each file in `examples/`, **then** `capellactl validate` exits 0 (with dummy env vars).

| Test | Location | Verifies |
|---|---|---|
| `test_docs_ac1_examples_validate` | `tests/unit/docs/test_examples.py` | Parametrised over files |

### AC2 — Every documented command parses
**Given** every fenced `capellactl …` command in `docs/*.md` and `README.md`, **then** it parses against the click tree (no unknown commands or flags).

| Test | Location | Verifies |
|---|---|---|
| `test_docs_ac2_commands_parse` | `tests/unit/docs/test_doc_commands.py` | |

### AC3 — Reference is generated and current
**Given** `make docs`, **then** `docs/reference.md` is regenerated from the schema and CI fails if the committed file differs.

| Test | Location | Verifies |
|---|---|---|
| `test_docs_ac3_reference_up_to_date` | `tests/unit/docs/test_reference.py` | |

### AC4 — Runbook covers the day-2 tasks
**Given** `docs/runbook.md`, **then** it has a section for each task in the table above, each with the exact command and expected output.

| Test | Location | Verifies |
|---|---|---|
| `test_docs_ac4_runbook_sections` | `tests/unit/docs/test_runbook.py` | Required headings present |

### AC5 — First environment by following the guide
**Given** an empty folder and an organization with no projects, **when** the steps of `getting-started.md` are run as written (configure → project create → cluster create → bucket create → credential create; and the "starting from scratch" path: init → validate → plan → apply), **then** every step succeeds without editing `capella.yaml` by hand, and the result is a healthy cluster with a bucket and an application credential, with no secret in the file and nothing left to change. The timed walkthrough by an engineer new to the tool (under 60 minutes, against a real organization) stays in the release checklist as a release check.

| Test | Location | Verifies |
|---|---|---|
| `test_docs_ac5_first_environment_from_scratch` | `tests/scenario/test_first_environment.py` | Guide steps 3, 4, 6, 8, 9 against the fake |
| `test_docs_ac5_first_environment_with_init` | same | `init` → `validate` → `plan` → `apply` |

## Out of scope
- Video tutorials.

## Open questions
- Will the docs be published (GitHub Pages, internal wiki) or shipped only in the repository? (Still open: for now they ship in the repository and in the source archive, CAP-043.)

## Implementation notes (as built)
- AC5 changed (2026-10-08): the manual timing became an automated end-to-end run of the guide against the fake
  Capella (two paths: create a project and cluster, or `init`), run in CI. The 60-minute walkthrough by a new
  engineer stays in the release checklist (INDEX.md) as a release check.
- The cheatsheet was merged into `docs/runbook.md` (2026-10-08) and removed: Part 1 day-2 tasks with expected
  output, Part 2 the command reference, Part 3 the 20-minute demo (Azure). README, getting-started and the CAP-042
  AC8 test point to the runbook.
- Found by AC5 and fixed: in an organization with no projects, `configure` answered "discover your projects?" with
  an error (exit 1) after saving the profile. It now says the organization has no projects yet and points to
  `capellactl project create NAME` (exit 0). The guide's "starting from scratch" path now shows `validate`, `plan`
  and `apply`, and says what to do in a new organization.
- Examples live in `docs/release-1.0.0/examples/` (where the reference example and the tests already were), not in
  a top-level `examples/`: `capella.yaml` (annotated reference), `single-node-dev.yaml`, `gcp-prod.yaml`,
  `azure-prod.yaml` and the earlier `minimal-cluster.yaml`.
- `docs/reference.md` is generated by `scripts/update-reference.py` (`make docs`) from the same schema walk as
  `capellactl help config`; `make check` and CI run `--check`. Enumerations longer than 12 values (timezones) show
  four examples and point to `capellactl help config FIELD`.
- `docs/runbook.md` Part 1: the expected output was captured by running each command against the fake Capella used
  by the scenario tests, then shortened (times, unchanged `=` lines).
- AC2 reuses the existing command-parsing test (CAP-018 AC7's helper), now over every `docs/*.md` (runbook
  included), the README and the built-in help pages.
- `docs/terraform.md` compares when to use capellactl or the Terraform provider and how to move between them.
- For a cluster in `deploymentFailed`, the plan says "delete it … and re-run apply", but `cluster delete` also
  removes the cluster from capella.yaml, so `apply` does not re-create it. The runbook gives the working steps
  (delete, then `cluster create`). The message is CAP-011 AC4's text, so changing it is left as a decision for
  CAP-011.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_docs_ac1_examples_validate` (tests/unit/docs/test_examples.py; parametrised over the examples) |
| AC2 | `test_docs_ac2_commands_parse` (tests/unit/docs/test_doc_commands.py) |
| AC3 | `test_docs_ac3_reference_up_to_date` (tests/unit/docs/test_reference.py) |
| AC4 | `test_docs_ac4_runbook_sections` (tests/unit/docs/test_runbook.py) |
| AC5 | `test_docs_ac5_first_environment_from_scratch`, `test_docs_ac5_first_environment_with_init` (tests/scenario/test_first_environment.py) |
