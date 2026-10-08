# CAP-017 — Vertical scaling: node compute & disk

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E4 Scaling | P0 | 3 | CAP-015 | Implemented |

## User story
As an **operator**, I want to change a service group's CPU/RAM or disk type, size and IOPS by editing the file, so that I can scale up without rebuilding the cluster.

## Context & discovery
- `serviceGroups[].node.compute{cpu*, ram*}` and `node.disk` are part of the cluster `PUT` body.
- Disk shapes per provider (spec `oneOf`): AWS `{type: gp3|io2, storage ≥ 50, iops}`; Azure `{type: P6…P60|Ultra, storage (Ultra only), iops (Ultra only), autoExpansion}`; GCP `{type: pd-ssd, storage ≥ 50}`.
- Vertical changes cause Capella to rebalance onto new nodes; the cluster goes through `scaling`/`rebalancing`.

## Implementation details
- `classify()` emits `VERTICAL` when `node.compute` or `node.disk` differ for the same group key.
- Disk storage **decrease** is treated as BLOCKED until confirmed supported (open question).
- A single apply may combine vertical and horizontal changes for different groups in one `PUT`; the plan shows each.

Plan output:
```
~ cluster nova-dev-01   scale up
    serviceGroups[data,index,query].node.compute:  4 vCPU/16 GB → 8 vCPU/32 GB
    serviceGroups[data,index,query].node.disk.storage:  50 → 100 GB
```

## Acceptance criteria & tests

### AC1 — Compute change
**Given** compute 4/16 → 8/32 for `data,index,query`, **then** one `PUT` with the new `compute` and all other group fields unchanged; waits for `healthy`.

| Test | Location | Verifies |
|---|---|---|
| `test_vertical_ac1_compute_change_body` | `tests/scenario/test_vertical_scaling.py` | |
| `test_scaling_classify_ac1_vertical` | `tests/unit/resources/test_scaling.py` | |

### AC2 — Disk change per provider
**Given** AWS `storage` 50 → 100 and `iops` 3000 → 6000, **then** the `PUT` has the new disk. **Given** Azure `P10` → `P20`, **then** the `PUT` has the new type without `storage`/`iops`. **Given** GCP `storage` 50 → 200, **then** the `PUT` has the new storage.

| Test | Location | Verifies |
|---|---|---|
| `test_vertical_ac2_disk_change_by_provider` | `tests/scenario/test_vertical_scaling.py` | Parametrised AWS/Azure/GCP |

### AC3 — Disk shrink blocked
**Given** `storage` 100 → 50, **then** `! … node.disk.storage: 100 → 50 GB  BLOCKED (disk size cannot be reduced)`, exit 4.

| Test | Location | Verifies |
|---|---|---|
| `test_vertical_ac3_disk_shrink_blocked` | `tests/scenario/test_vertical_scaling.py` | |

### AC4 — Disk type must match provider
**Given** an AWS cluster with disk type `P20`, **then** `validate` exits 3.

| Test | Location | Verifies |
|---|---|---|
| `test_vertical_validate_ac4_disk_type_provider` | `tests/unit/config/test_scaling_rules.py` | |

### AC5 — Combined with horizontal change
**Given** compute change on `data,index,query` and +2 nodes on `search` in one file edit, **then** one `PUT` carries both, and the plan labels `scale up` and `scale out` lines separately.

| Test | Location | Verifies |
|---|---|---|
| `test_vertical_ac5_combined_single_put` | `tests/scenario/test_vertical_scaling.py` | Exactly one PUT |

### AC6 — Memory guard on compute decrease
**Given** RAM per node decreases (32 → 16 GB) on the data group, **then** the memory guard from CAP-016 runs with `projected = total × newRam / oldRam` and blocks when buckets would not fit.

| Test | Location | Verifies |
|---|---|---|
| `test_vertical_ac6_ram_decrease_memory_guard` | `tests/scenario/test_vertical_scaling.py` | |

### AC7 — Idempotent re-run
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_vertical_ac7_rerun_zero_writes` | `tests/scenario/test_vertical_scaling.py` | |

## Out of scope
- Recommending instance sizes.

## Open questions
- Does Capella allow decreasing disk storage? If yes, relax AC3 to a warning.
- Is IOPS change on AWS `gp3` applied without node replacement? (Affects expected duration only.)

## Implementation notes (as built)
- AC6 (2026-10-07, with CAP-016): a RAM decrease on a data group runs the memory guard with `projected = total × new data memory / old data memory`; it used to be refused outright.
- AC1–AC5 and AC7 are done. AC6 (memory guard on a RAM decrease) needs the CAP-016 capacity checks; until then any RAM decrease is BLOCKED, so it can never slip through as 'scale up'.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_vertical_ac1_compute_change_body` (tests/scenario/test_vertical_scaling.py)<br>`test_scaling_classify_ac1_vertical` (tests/scenario/test_vertical_scaling.py) |
| AC2 | `test_vertical_ac2_disk_change_by_provider` (tests/scenario/test_vertical_scaling.py) |
| AC3 | `test_vertical_ac3_disk_shrink_blocked` (tests/scenario/test_vertical_scaling.py) |
| AC4 | `test_vertical_validate_ac4_disk_type_provider` (tests/scenario/test_vertical_scaling.py) |
| AC5 | `test_vertical_ac5_combined_single_put` (tests/scenario/test_vertical_scaling.py) |
| AC6 | `test_vertical_ac6_ram_decrease_memory_guard` (tests/scenario/test_vertical_scaling.py) |
| AC7 | `test_vertical_ac7_rerun_zero_writes` (tests/scenario/test_vertical_scaling.py) |
