# CAP-018 — Step scaling command with min/max guardrails

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E4 Scaling | P1 | 3 | CAP-016 | Implemented |

## User story
As an **operator who uses the Nova `scale_capella_cluster.sh` script**, I want `capellactl cluster scale --step +1/-1` with minimum and maximum node limits, so that schedulers, alerts and runbooks can add or remove one node at a time without editing files.

## Context & discovery
The Nova script (`--scale-up` / `--scale-down`, `MIN_NODE_COUNT=3`, `MAX_NODE_COUNT=6`):
- reads `serviceGroups[].numOfNodes`, sums them as "current node count";
- sets **every** group to current ± 1;
- exits 0 with a message at the limit;
- checks errors with `grep '"error"'` on the response.

This story keeps the behaviour operators rely on (step, limits, exit 0 at limit) and fixes two issues: per-group targeting instead of setting every group to the summed count, and structured error handling (CAP-003).

## Implementation details
```
capellactl cluster scale NAME --step +1|-1 [--group SERVICES] [--min 3] [--max 6] [--all-groups]
```
- Default group: the one running `data`. `--all-groups` applies the step to each group individually (each group ±1, not set to a sum).
- `--min` defaults to the group minimum (3 first group / 2 others); `--max` defaults to the group maximum.
- Scale-in steps run all CAP-016 guards.
- Machine-readable: `-o json` → `{"cluster","group","from","to","status":"scaled|at_limit|blocked"}`.

## Acceptance criteria & tests

### AC1 — Step up
**Given** 3 nodes in the data group and `--step +1 --max 6`, **then** one `PUT` with 4 nodes; output `scaled data,index,query: 3 → 4`.

| Test | Location | Verifies |
|---|---|---|
| `test_step_ac1_step_up` | `tests/scenario/test_step_scaling.py` | |

### AC2 — Step down with guards
**Given** 4 nodes and `--step -1 --min 3`, **then** guards from CAP-016 run, and on pass one `PUT` with 3 nodes. **Given** a guard fails, **then** exit 4 and `status: blocked`.

| Test | Location | Verifies |
|---|---|---|
| `test_step_ac2_step_down_runs_guards` | `tests/scenario/test_step_scaling.py` | |
| `test_step_ac2_step_down_guard_blocks` | same | |

### AC3 — At limit is success with no write
**Given** 6 nodes and `--step +1 --max 6`, **then** `already at maximum (6)`, exit 0, zero writes, `status: at_limit`. Same for `--min` on step down.

| Test | Location | Verifies |
|---|---|---|
| `test_step_ac3_at_max_noop` | `tests/scenario/test_step_scaling.py` | |
| `test_step_ac3_at_min_noop` | same | |

### AC4 — All groups stepped individually
**Given** groups `data,index,query`=3 and `search`=2 and `--all-groups --step +1`, **then** the `PUT` has 4 and 3 (not both set to 6 as the Nova script would).

| Test | Location | Verifies |
|---|---|---|
| `test_step_ac4_all_groups_individual` | `tests/scenario/test_step_scaling.py` | |

### AC5 — Busy cluster
**Given** the cluster is already `scaling`, **then** the command waits for `healthy` (or with `--no-wait` exits 4 `cluster is scaling; try again later`) and only then computes the step from the new count.

| Test | Location | Verifies |
|---|---|---|
| `test_step_ac5_waits_when_busy` | `tests/scenario/test_step_scaling.py` | |
| `test_step_ac5_no_wait_busy_exit_4` | same | |

### AC6 — JSON output for automation
**Given** `-o json`, **then** the output validates against `tests/schemas/scale.schema.json` for each status.

| Test | Location | Verifies |
|---|---|---|
| `test_step_ac6_json_output` | `tests/scenario/test_step_scaling.py` | |

### AC7 — Nova script parity doc
**Given** `docs/migrating-from-scale-script.md`, **then** it maps each script flag to a `capellactl` command and documents the per-group difference.

| Test | Location | Verifies |
|---|---|---|
| `test_docs_ac7_migration_guide_commands_valid` | `tests/unit/docs/test_doc_commands.py` | Every command in the guide parses with `--help` |

## Out of scope
- Metric-driven autoscaling.

## Open questions
- Should `--update-config` rewrite `numOfNodes` in `capella.yaml` (preserving comments, via `ruamel.yaml`) so the file stays the source of truth? Proposed for 1.1.

## Implementation notes (as built)
- `capellactl cluster scale NAME --step +1|-1 [--group SERVICES | --all-groups] [--min N] [--max N]` (`cli/cluster_ops.py::step_scale`). The step starts from the node count Capella has now, writes the new count to capella.yaml and applies it through the same path as `--nodes`, so scale-down runs the CAP-016 checks.
- Default limits: first group 3–27, other groups 2–24, single-node clusters 1.
- `-o json` prints only the JSON document (the plan text is muted): one object, or an array with `--all-groups`, validated by `tests/schemas/scale.schema.json`; `status` is `scaled`, `at_limit`, `blocked` (exit 4) or `cancelled`.
- The open question is settled: the new count is always recorded in capella.yaml (no `--update-config` flag), like every other command (CAP-038).
- AC7 guide: [docs/migrating-from-scale-script.md](../migrating-from-scale-script.md); its test checks that each command exists and every option it uses is valid.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_step_ac1_step_up` (tests/scenario/test_step_scaling.py) |
| AC2 | `test_step_ac2_step_down_runs_guards` (tests/scenario/test_step_scaling.py)<br>`test_step_ac2_step_down_guard_blocks` (tests/scenario/test_step_scaling.py) |
| AC3 | `test_step_ac3_at_max_noop` (tests/scenario/test_step_scaling.py)<br>`test_step_ac3_at_min_noop` (tests/scenario/test_step_scaling.py) |
| AC4 | `test_step_ac4_all_groups_individual` (tests/scenario/test_step_scaling.py) |
| AC5 | `test_step_ac5_waits_when_busy` (tests/scenario/test_step_scaling.py)<br>`test_step_ac5_no_wait_busy_exit_4` (tests/scenario/test_step_scaling.py) |
| AC6 | `test_step_ac6_json_output` (tests/scenario/test_step_scaling.py) |
| AC7 | `test_docs_ac7_migration_guide_commands_valid` (tests/unit/docs/test_doc_commands.py) |

