# CAP-015 — Scale out: add nodes & service groups

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E4 Scaling | P0 | 5 | CAP-011 | Implemented |

## User story
As an **operator**, I want to add nodes to a service group, or add a new service group (for example dedicated `search` nodes), by editing the file or with one command, so that I can add capacity predictably and with the same safety checks every time.

## Context & discovery
- Scaling is a `PUT …/clusters/{clusterId}` with the full `serviceGroups` list (plus `name`, `description`, `support`), `204`, then `currentState` goes `scaling`/`rebalancing` → `healthy`.
- Limits from the spec ([00-architecture.md §7.1](00-architecture.md#71-limits-from-the-api-spec)): first group 3–27 nodes; additional groups 2–24; `singleNode` has exactly 1 node.
- `GET …/clusters/{id}` also returns `expressScaling` (`enabled`/`disabled`); read-only, shown in `cluster get`.
- Service groups are identified by their sorted services set (the *group key*), e.g. `data,index,query`.

## Implementation details

### Declarative
```yaml
serviceGroups:
  - node: { compute: { cpu: 4, ram: 16 }, disk: { type: gp3, storage: 50, iops: 3000 } }
    numOfNodes: 5                       # was 3 → scale out
    services: [data, index, query]
  - node: { compute: { cpu: 4, ram: 16 }, disk: { type: gp3, storage: 50, iops: 3000 } }
    numOfNodes: 2                       # new group → scale out
    services: [search]
```

### Imperative
```
capellactl cluster scale nova-dev-01 --nodes 5 [--group data,index,query]
```
`--group` defaults to the group containing `data` (if exactly one does).

### Planning (`resources/scaling.py`)
`classify(observed_groups, desired_groups) -> list[ScaleChange]` with kinds `OUT_NODES`, `OUT_GROUP`, `IN_NODES`, `IN_GROUP` (CAP-016), `VERTICAL` (CAP-017). A change to a group's `services` set is emitted as `IN_GROUP(old)` + `OUT_GROUP(new)`.

Plan output:
```
~ cluster nova-dev-01   scale out
    serviceGroups[data,index,query].numOfNodes:  3 → 5
  + serviceGroups[search]  2 × 4 vCPU/16 GB gp3 50 GB
    total nodes: 3 → 7
```

## Acceptance criteria & tests

### AC1 — Add nodes to a group (declarative)
**Given** `numOfNodes` 3 → 5 for `data,index,query`, **then** the plan shows the change with `scale out`, one `PUT` is sent whose `serviceGroups` equals observed groups with that group's `numOfNodes: 5`, and apply waits for `healthy`.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_out_ac1_add_nodes_body` | `tests/scenario/test_scale_out.py` | PUT body |
| `test_scaling_classify_ac1_out_nodes` | `tests/unit/resources/test_scaling.py` | |

### AC2 — Add a service group
**Given** a new `search` group with 2 nodes, **then** the `PUT` body contains all existing groups unchanged plus the new group; the plan line is `+ serviceGroups[search]`.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_out_ac2_add_group_body` | `tests/scenario/test_scale_out.py` | |
| `test_scaling_classify_ac2_out_group` | `tests/unit/resources/test_scaling.py` | |

### AC3 — Group order and service order do not matter
**Given** the file lists groups and services in a different order than Capella, and only `numOfNodes` changed, **then** the classification is exactly one `OUT_NODES` change.

| Test | Location | Verifies |
|---|---|---|
| `test_scaling_classify_ac3_order_insensitive` | `tests/unit/resources/test_scaling.py` | |

### AC4 — Limits enforced offline
**Given** an additional group with `numOfNodes: 25`, or first group `28`, or a `singleNode` cluster with `numOfNodes: 2`, **then** `validate` exits 3 naming the rule (`additional service groups allow 2–24 nodes`, `singleNode clusters have exactly 1 node; create a multiNode cluster to scale out`).

| Test | Location | Verifies |
|---|---|---|
| `test_scale_out_validate_ac4_limits` | `tests/unit/config/test_scaling_rules.py` | Parametrised |

### AC5 — Imperative command
**Given** `cluster scale nova-dev-01 --nodes 5`, **then** the target group is the one containing `data`, the plan is shown, and after confirmation the same `PUT` as AC1 is sent. **Given** two groups contain `data` and no `--group`, **then** exit 3 `more than one group runs data; pass --group`.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_cli_ac5_nodes_defaults_to_data_group` | `tests/scenario/test_scale_cli.py` | |
| `test_scale_cli_ac5_ambiguous_group` | same | |

### AC6 — Imperative scale keeps capella.yaml in step
**Given** the file declares 3 nodes and `cluster scale --nodes 5` succeeds, **then** capella.yaml now declares 5 for that group, and a later `plan` reports no changes. *(Revised by CAP-038: capella.yaml is tool-owned, so commands record their changes instead of printing a drift note.)*

| Test | Location | Verifies |
|---|---|---|
| `test_scale_cli_ac6_file_updated_no_drift` | `tests/scenario/test_scale_out.py` | |

### AC7 — Only when healthy; failure reported
**Given** the cluster is `turnedOff`, **then** `! cluster nova-dev-01  turned off; power it on before scaling`, exit 4. **Given** the scale ends in `scaleFailed`, **then** exit 1 with the activity-log hint.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_out_ac7_turned_off_blocked` | `tests/scenario/test_scale_out.py` | |
| `test_scale_out_ac7_scale_failed` | same | |

### AC8 — Idempotent re-run
**Given** AC1 completed, **then** a re-run (and `cluster scale --nodes 5` again) makes zero writes and prints `already at 5 nodes`.

| Test | Location | Verifies |
|---|---|---|
| `test_scale_out_ac8_rerun_zero_writes` | `tests/scenario/test_scale_out.py` | |
| `test_scale_cli_ac8_same_count_noop` | `tests/scenario/test_scale_cli.py` | |
| `test_scale_out_ac8_integration` | `tests/integration/test_scaling.py` | 3 → 4 nodes on sandbox |

## Out of scope
- Autoscaling based on metrics.
- Scaling App Services.

## Open questions
- Is the 27-node maximum per cluster (sum of groups) or per group? The spec text is ambiguous; validation currently enforces both. Confirm with Capella docs/support.
- For `availability: multi`, must node counts be multiples of the AZ count? Confirm in sandbox; add a validation rule if so.

## Implementation notes (as built)
- `cluster scale NAME --nodes N [--group SERVICES]` is implemented; `--step/--min/--max/--all-groups` belong to CAP-018 and report that they are not available yet.
- Scale-in (fewer nodes or a removed group) is BLOCKED with a pointer to CAP-016 until the capacity checks exist. AC8's sandbox check is part of CAP-032.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_scale_out_ac1_add_nodes_body` (tests/scenario/test_scale_out.py)<br>`test_scaling_classify_ac1_out_nodes` (tests/scenario/test_scale_out.py) |
| AC2 | `test_scale_out_ac2_add_group_body` (tests/scenario/test_scale_out.py)<br>`test_scaling_classify_ac2_out_group` (tests/scenario/test_scale_out.py) |
| AC3 | `test_scaling_classify_ac3_order_insensitive` (tests/scenario/test_scale_out.py) |
| AC4 | `test_scale_out_validate_ac4_limits` (tests/scenario/test_scale_out.py) |
| AC5 | `test_scale_cli_ac5_nodes_defaults_to_data_group` (tests/scenario/test_scale_out.py)<br>`test_scale_cli_ac5_ambiguous_group` (tests/scenario/test_scale_out.py) |
| AC6 | `test_scale_cli_ac6_file_updated_no_drift` (tests/scenario/test_scale_out.py) |
| AC7 | `test_scale_out_ac7_turned_off_blocked` (tests/scenario/test_scale_out.py)<br>`test_scale_out_ac7_scale_failed` (tests/scenario/test_scale_out.py) |
| AC8 | `test_scale_out_ac8_rerun_zero_writes` (tests/scenario/test_scale_out.py)<br>`test_scale_cli_ac8_same_count_noop` (tests/scenario/test_scale_out.py) |
