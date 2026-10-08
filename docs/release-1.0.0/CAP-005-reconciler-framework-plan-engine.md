# CAP-005 — Reconciler framework & plan engine

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P0 | 8 | CAP-002, CAP-003 | Implemented |

## User story
As an **operator**, I want to see exactly what will change before it changes, with the same view for every resource, so that I can run the tool safely in production and in CI.

## Context & discovery
- The tool is stateless: plan = desired (file) vs observed (live API) for every resource ([00-architecture.md §3](00-architecture.md#3-design-principles)).
- False differences break idempotency; normalisation rules are in [00-architecture.md §6.3](00-architecture.md#63-comparison-rules-enginenormalizepy).
- Names are not unique for projects and clusters in Capella, so lookup must detect ambiguity.

## Implementation details

| Module | Responsibility |
|---|---|
| `resources/base.py` | `Reconciler` protocol, `Action`, `Change`, `ParentIds`, `Observed(body, etag)` |
| `engine/normalize.py` | `normalize(kind, desired, observed) -> (d, o)` applying §6.3 |
| `engine/diff.py` | `field_changes(d, o, only_keys=desired_keys) -> list[Change]` |
| `engine/graph.py` | Topological order from [§4.2](00-architecture.md#42-dependency-order); reverse order for deletes |
| `engine/planner.py` | `build_plan(model, client, targets) -> Plan`; calls `observe` once per parent; collects actions; marks children `DEFERRED` when parent is not ready |
| `output/render.py` | `render_plan_text(plan)`, `render_plan_json(plan)` |
| `cli/env.py` | `plan` command |

## Acceptance criteria & tests

### AC1 — Plan lines and symbols
**Given** a desired state with one new bucket, one changed cluster field and one unchanged scope, **when** `capellactl plan` runs, **then** the output contains `+ bucket nova-dev-01/orders`, `~ cluster nova-dev-01` followed by `    serviceGroups[data,index,query].numOfNodes:  3 → 5`, and `= scope nova-dev-01/orders/inventory`, followed by `Plan: 1 to add, 1 to change, 0 to delete, 0 blocked.`

| Test | Location | Verifies |
|---|---|---|
| `test_plan_ac1_symbols_and_summary` | `tests/scenario/test_plan.py` | Golden-file output |
| `test_render_ac1_each_action_type_symbol` | `tests/unit/output/test_render.py` | All 7 symbols from §5.2 |

### AC2 — Plan is read-only
**Given** any plan, **then** only `GET` requests are sent.

| Test | Location | Verifies |
|---|---|---|
| `test_plan_ac2_only_get_requests` | `tests/scenario/test_plan.py` | `fake.writes() == []` |

### AC3 — Only declared fields compared, defaults applied
**Given** a bucket in the file without `priority`, and Capella has `priority: 5`, **then** no change is planned. **Given** a bucket without `replicas` (default 1) and Capella has `replicas: 2`, **then** `~ replicas: 2 → 1` is planned.

| Test | Location | Verifies |
|---|---|---|
| `test_normalize_ac3_undeclared_field_ignored` | `tests/unit/engine/test_normalize.py` | |
| `test_normalize_ac3_default_compared` | same | |

### AC4 — Normalisation rules
**Given** the observed/desired pairs below, **then** no change is planned for each: services in a different order; service groups in a different order; privileges `read` vs `data_reader`; `support.plan` `Developer Pro` vs `developer pro`; observed `flush: false` with no `flushEnabled`.

| Test | Location | Verifies |
|---|---|---|
| `test_normalize_ac4_equivalences` | `tests/unit/engine/test_normalize.py` | Parametrised table |

### AC5 — Ambiguous name
**Given** two clusters named `nova-dev-01` in the project, **then** the plan shows `! cluster nova-dev-01  2 clusters share this name (ids: c-1, c-2); add id: to choose one` and `plan --detailed-exitcode` exits 4.

| Test | Location | Verifies |
|---|---|---|
| `test_planner_ac5_ambiguous_name_blocked` | `tests/scenario/test_plan.py` | Also for projects |

### AC6 — Deferred children
**Given** a new cluster (not yet created), **then** its buckets, scopes, collections, credentials, CIDRs and schedule appear as `+` with the note `(after cluster is healthy)` and no `GET` is made for children of a cluster that does not exist.

| Test | Location | Verifies |
|---|---|---|
| `test_planner_ac6_children_of_new_cluster` | `tests/scenario/test_plan.py` | |

### AC7 — Target filter
**Given** `plan --target bucket/nova-dev-01/orders`, **then** only that bucket (and read-only lookups of its parents) is planned.

| Test | Location | Verifies |
|---|---|---|
| `test_planner_ac7_target_filter` | `tests/scenario/test_plan.py` | |

### AC8 — JSON output and detailed exit code
**Given** `plan -o json`, **then** the output validates against `tests/schemas/plan.schema.json`. **Given** `--detailed-exitcode`, **then** exit 0 with no changes, 2 with changes, 4 if anything is blocked.

| Test | Location | Verifies |
|---|---|---|
| `test_plan_ac8_json_schema` | `tests/scenario/test_plan.py` | |
| `test_plan_ac8_detailed_exitcode` | same | Three cases |

## Out of scope
- Executing the plan (CAP-006).

## Open questions
- None.

## Implementation notes (as built)
- Kinds not managed by this build (deletion protection, schedule, CIDRs, buckets/scopes/collections, credentials) are planned as one `…` deferred line per kind per cluster, naming the story that will deliver them; they never cause API calls or writes.
- Engine tests use test-only reconcilers (`tests/fakes/stub_reconcilers.py`) for buckets, scopes, collections, CIDRs and credentials, plugged in through `capellactl.cli.env.TREE_FACTORY`.
- `--target project/NAME` is used by `project update` (and the hidden `project apply` alias) without descendants (planner option `descendants=False`).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_plan_ac1_symbols_and_summary` (tests/scenario/test_plan.py)<br>`test_render_ac1_each_action_type_symbol` (tests/unit/output/test_render.py) |
| AC2 | `test_plan_ac2_only_get_requests` (tests/scenario/test_plan.py) |
| AC3 | `test_normalize_ac3_undeclared_field_ignored` (tests/unit/engine/test_normalize.py)<br>`test_normalize_ac3_default_compared` (tests/unit/engine/test_normalize.py) |
| AC4 | `test_normalize_ac4_equivalences` (tests/unit/engine/test_normalize.py)<br>`test_normalize_ac4_privilege_aliases` (tests/unit/engine/test_normalize.py)<br>`test_normalize_ac4_flush_fallback` (tests/unit/engine/test_normalize.py) |
| AC5 | `test_planner_ac5_ambiguous_name_blocked` (tests/scenario/test_plan.py)<br>`test_planner_ac5_ambiguous_project_blocked` (tests/scenario/test_plan.py) |
| AC6 | `test_planner_ac6_children_of_new_cluster` (tests/scenario/test_plan.py)<br>`test_planner_ac6_unsupported_kinds_deferred` (tests/scenario/test_plan.py) |
| AC7 | `test_planner_ac7_target_filter` (tests/scenario/test_plan.py) |
| AC8 | `test_plan_ac8_json_schema` (tests/scenario/test_plan.py)<br>`test_plan_ac8_detailed_exitcode` (tests/scenario/test_plan.py) |
