# CAP-033 — Examples, runbook & customer documentation

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P0 | 3 | CAP-030 | Not started |

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

### AC5 — Time-to-first-environment
**Given** a customer engineer who has not used the tool, **when** they follow `getting-started.md`, **then** they reach a healthy cluster with a bucket and credential in under 60 minutes of their time (measured once, manually, before release).

| Test | Location | Verifies |
|---|---|---|
| Manual check recorded in the release checklist | `INDEX.md` | |

## Out of scope
- Video tutorials.

## Open questions
- Will the docs be published (GitHub Pages, internal wiki) or shipped only in the repository?
