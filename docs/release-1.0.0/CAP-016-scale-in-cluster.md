# CAP-016 — Scale in: remove nodes & service groups safely

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E4 Scaling | P0 | 5 | CAP-015 | Implemented |

## User story
As an **operator**, I want to remove nodes or a whole service group to save cost, and have the tool refuse a scale-in that would leave the cluster without enough memory, replicas or services, so that cost savings never cause an outage.

## Context & discovery
- Same `PUT …/clusters/{clusterId}` as scale out (CAP-015).
- `GET …/clusters/{clusterId}/stats` returns `totalMemoryInMb`, `freeMemoryInMb`, `maxReplicas` — *"cluster capacity information … allowing clients to make informed decisions when managing buckets"*.
- `GET …/buckets` returns each bucket's `replicas` and `memoryAllocationInMb`.
- Guards: [00-architecture.md §7.2](00-architecture.md#72-scale-in-guards-get-clustersidstats).

## Implementation details

`resources/scaling.py::check_scale_in(observed_cluster, desired_groups, stats, buckets) -> list[GuardResult]`:

| Guard | Computation | Message when violated |
|---|---|---|
| Memory | `allocated = total − free`; `projected = total × m / n` (m, n = new and current nodes running `data`) | `scale-in blocked: buckets allocate 18,432 MB but data service would have ~16,384 MB after scale-in (5 → 4 nodes)` |
| Replicas | `max(bucket.replicas) ≤ m − 1` | `scale-in blocked: bucket 'orders' has 2 replicas and needs at least 3 data nodes` |
| Data service | at least one group keeps `data` | `scale-in blocked: removing the last group that runs data` |
| Other services | last group running `index`/`query`/`search`/`analytics`/`eventing` removed | blocked unless `--allow-service-removal` |
| Group removal | whole group removed | needs `--allow-service-group-removal` in addition to confirmation |
| Minimums | first group ≥ 3, others ≥ 2 | offline validation (exit 3) |

Imperative: `capellactl cluster scale nova-dev-01 --nodes 3 [--group …]`.

Plan output:
```
~ cluster nova-dev-01   scale in
    serviceGroups[data,index,query].numOfNodes:  5 → 4
    checks: memory ok (12,288 / ~16,384 MB) · replicas ok (max 1, needs 2 data nodes)
```

## Acceptance criteria & tests

### AC1 — Remove nodes when guards pass
**Given** 5 data nodes, `stats` total 20,480 MB / free 8,192 MB, max bucket replicas 1, and the file says 4 nodes, **then** the plan shows `scale in` with `checks: memory ok … replicas ok …`, confirmation lists it under `Destructive changes:`, and one `PUT` with `numOfNodes: 4` is sent.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_in_ac1_guards_pass_put_sent` | `tests/scenario/test_scale_in.py` | |
| `test_scale_in_guard_ac1_memory_math` | `tests/unit/resources/test_scale_in_guards.py` | |

### AC2 — Memory guard blocks
**Given** total 20,480 MB, free 2,048 MB (allocated 18,432) and 5 → 4 nodes (projected 16,384), **then** `! … scale-in blocked: buckets allocate 18,432 MB but data service would have ~16,384 MB after scale-in (5 → 4 nodes)`, exit 4, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_in_ac2_memory_guard_blocks` | `tests/scenario/test_scale_in.py` | |
| `test_scale_in_guard_ac2_boundary_equal_allowed` | `tests/unit/resources/test_scale_in_guards.py` | allocated == projected passes |

### AC3 — Replica guard blocks
**Given** bucket `orders` with `replicas: 2` and 4 → 2 data nodes, **then** blocked with the replica message, exit 4.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_in_ac3_replica_guard_blocks` | `tests/scenario/test_scale_in.py` | |

### AC4 — Removing a service group
**Given** the `search` group is removed from the file, **then** without flags: `! … removing serviceGroups[search] removes the last search nodes; pass --allow-service-removal --allow-service-group-removal`, exit 4. **With** both flags and confirmation, **then** the `PUT` omits that group.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_in_ac4_group_removal_needs_flags` | `tests/scenario/test_scale_in.py` | |
| `test_scale_in_ac4_group_removal_with_flags` | same | Body without search group |

### AC5 — Last data group is never removed
**Given** a change that removes the only group running `data` (including changing its `services` so `data` disappears), **then** blocked regardless of flags.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_in_ac5_last_data_group_never_removed` | `tests/scenario/test_scale_in.py` | |

### AC6 — Auto-approve still needs explicit group-removal flag
**Given** `apply --auto-approve` with a group removal but without `--allow-service-group-removal`, **then** exit 4, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_in_ac6_auto_approve_not_enough_for_group_removal` | `tests/scenario/test_scale_in.py` | |

### AC7 — Stats unavailable
**Given** `GET …/stats` fails (403 or 5xx after retries), **then** scale-in is blocked with `cannot verify capacity (stats unavailable); pass --skip-capacity-check to proceed at your own risk`.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_in_ac7_stats_unavailable_blocks` | `tests/scenario/test_scale_in.py` | |
| `test_scale_in_ac7_skip_capacity_check` | same | |

### AC8 — Idempotent re-run
**Given** AC1 completed, **then** a re-run makes zero writes (and does not call `stats` again, because no scale-in is planned).

| Test | Location | Verifies |
|---|---|---|
| `test_scale_in_ac8_rerun_zero_writes_no_stats_call` | `tests/scenario/test_scale_in.py` | |
| `test_scale_in_ac8_integration` | `tests/integration/test_scaling.py` | 4 → 3 nodes on sandbox |

## Out of scope
- Estimating index or search memory requirements (only data-service memory is checked).

## Open questions
- Does `totalMemoryInMb` represent the data-service quota (used here) or all services? Confirm in sandbox; adjust the projection formula if needed.
- Does `maxReplicas` already reflect node count? If so, use it directly for the replica guard.

## Implementation notes (as built)
- `capellactl/resources/scaling.py` holds the guards; the cluster reconciler runs them whenever a change lowers the data service's capacity (fewer data nodes, less RAM per data node, a removed group). The memory projection is `total × new data memory / old data memory` with data memory = Σ data nodes × RAM, which is `total × m / n` for a node change and also covers RAM decreases (CAP-017 AC6).
- Flags on `apply`: `--allow-service-removal`, `--allow-service-group-removal`, `--skip-capacity-check`; `cluster scale` takes `--skip-capacity-check` (it never removes a group).
- AC3: the story's example (4 → 2 data nodes) is refused offline by the minimum node rule (first group 3–27), so the test uses 3 replicas and 4 → 3 nodes.
- AC5: removing `data` from the file is refused by offline validation (exit 3, `at least one service group must run the data service`) before any call; the runtime guard blocks it too, whatever the flags (unit test).
- AC6: a group removal that loses no service still needs `--allow-service-group-removal`; `--auto-approve` is never enough.
- The plan shows the result under the changes: `checks: memory ok (12,288 / ~16,384 MB) · replicas ok (max 1, needs 2 data nodes)`; scale-in is listed under *Destructive changes* before the confirmation.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_scale_in_ac1_guards_pass_put_sent` (tests/scenario/test_scale_in.py)<br>`test_scale_cli_scale_in_runs_guards` (tests/scenario/test_scale_out.py)<br>`test_scale_in_guard_ac1_memory_math` (tests/unit/resources/test_scale_in_guards.py) |
| AC2 | `test_scale_in_ac2_memory_guard_blocks` (tests/scenario/test_scale_in.py)<br>`test_scale_in_guard_ac2_boundary_equal_allowed` (tests/unit/resources/test_scale_in_guards.py) |
| AC3 | `test_scale_in_ac3_replica_guard_blocks` (tests/scenario/test_scale_in.py) |
| AC4 | `test_scale_in_ac4_group_removal_needs_flags` (tests/scenario/test_scale_in.py)<br>`test_scale_in_ac4_group_removal_with_flags` (tests/scenario/test_scale_in.py) |
| AC5 | `test_scale_in_ac5_last_data_group_never_removed` (tests/scenario/test_scale_in.py)<br>`test_scale_in_guard_ac5_no_data_left_whatever_flags` (tests/unit/resources/test_scale_in_guards.py) |
| AC6 | `test_scale_in_ac6_auto_approve_not_enough_for_group_removal` (tests/scenario/test_scale_in.py) |
| AC7 | `test_scale_in_ac7_stats_unavailable_blocks` (tests/scenario/test_scale_in.py)<br>`test_scale_in_ac7_skip_capacity_check` (tests/scenario/test_scale_in.py) |
| AC8 | `test_scale_in_ac8_integration` (tests/integration/test_scaling.py)<br>`test_scale_in_ac8_rerun_zero_writes_no_stats_call` (tests/scenario/test_scale_in.py) |

