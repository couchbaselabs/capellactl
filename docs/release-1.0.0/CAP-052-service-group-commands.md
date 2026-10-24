# CAP-052 — Service group commands: list, add and remove groups on an existing cluster

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E4 Scaling | P1 | 5 | CAP-015, CAP-016, CAP-038, CAP-051 | Implemented |

## User story
As an **operator**, I want to see a cluster's service groups, add a new group (for example dedicated `search` nodes) and remove one, each with one command, so that I can change a cluster's service layout after it is deployed without editing capella.yaml.

## Context & discovery
- CAP-015 AC2 (add a group) and CAP-016 (remove a group, guarded) are built in the engine, but are reachable only by editing capella.yaml and running `apply`. That breaks the tool-owned-file decision (CAP-038). `cluster scale --group` and `cluster update --group` only change existing groups; `cluster scale --nodes` accepts 1–27, so it cannot remove a group either.
- API: the same `PUT …/clusters/{clusterId}` with the full `serviceGroups` list (CAP-015), `204`, then `scaling`/`rebalancing` → `healthy`; the group list is read with `GET …/clusters/{clusterId}`. **No new endpoint.**
- Classification (`resources/scaling.py`) already has `OUT_GROUP` and `IN_GROUP`; the CAP-016 guards and flags (`--allow-service-removal`, `--allow-service-group-removal`, `--skip-capacity-check`) already apply to `IN_GROUP`.

## Design

### Commands
```
capellactl cluster group list   NAME
capellactl cluster group add    NAME --services SERVICES [--nodes N] [--cpu N] [--ram N]
                                     [--disk-type T] [--disk-size GB] [--disk-iops N] [--disk-auto-expansion]
capellactl cluster group remove NAME SERVICES [--allow-service-removal] [--skip-capacity-check]
```
Shared flags as for every cluster command: `--project`, `--no-apply`, global `--auto-approve`, `--no-wait`, `-o json`.

Examples:
```
capellactl cluster group list nova-prod-01
capellactl cluster group add nova-prod-01 --services search --nodes 2
capellactl cluster group add nova-prod-01 --services index,query --nodes 2 --cpu 16 --ram 64
capellactl cluster group remove nova-prod-01 search
```

- `cluster group` is a new sub-group of `cluster`, like `cluster schedule`. Each verb follows the CAP-038 flow: change the entry → validate → plan → confirm → write → apply.
- **list**: one row per group, in the list layout every list uses (S.NO first): `S.NO  SERVICES  NODES  vCPU  RAM GB  DISK` (disk as `gp3 50 GB 3000 IOPS`), then `total nodes: 7 of 27`. Read from Capella (`GET …/clusters/{id}`), so it is right even before a `sync`.
- **add**: `--services` is required. Options not given are copied from the group that runs `data` (compute and disk); `--nodes` defaults to 2 (the minimum for an additional group). Interactive terminals are asked for services and nodes, with those defaults. The group key must be new; if a group with the same services exists:
  - with the same size → `already exists` (exit 0, no writes), so scripts can re-run;
  - with a different size → exit 3 `group index,query exists with 2 × 8/32; use 'cluster scale' or 'cluster update --group index,query'`.
- **remove**: `SERVICES` is the group key in any order. The plan shows the CAP-016 capacity checks. Removing a group is a deliberate act, so `remove` itself is the opt-in that `apply` requires as `--allow-service-group-removal`; `--auto-approve` is enough for scripts. Removing the last group that runs a service still needs `--allow-service-removal`; the last data group is refused.

### Plan output
```
~ cluster nova-prod-01   scale out
  + serviceGroups[search]  2 × 8 vCPU/32 GB gp3 50 GB 3000 IOPS
    total nodes: 5 → 7
```
```
~ cluster nova-prod-01   scale in
  - serviceGroups[search]  2 × 8 vCPU/32 GB
    checks: memory ok · replicas ok · search: last group running it (--allow-service-removal given)
    total nodes: 7 → 5
```

### Where the code goes
- `cli/cluster_group.py` (new): the `group` sub-group with `list`, `add`, `remove`, registered in `_register_cluster_ops()`.
- `config/editor.py`: `add_group(cluster, group)` and `remove_group(cluster, key)` next to the existing `group()`.
- Reuses `change_and_apply`, `scale_in_file`'s guard options, and the CAP-051 disk defaults.

## Acceptance criteria & tests

### AC1 — List groups
**Given** a cluster with three groups, **then** `cluster group list` prints a row per group with S.NO first and the total, and `-o json` returns the groups as Capella reports them. **Given** an unknown cluster, **then** exit 1 with the usual `cluster NAME not found` message.

| Test | Location | Verifies |
|---|---|---|
| `test_group_cmd_ac1_list` | `tests/scenario/test_cluster_group.py` | Text and JSON |

### AC2 — Add a group
**Given** `cluster group add nova-dev-01 --services search --nodes 2`, **then** one `PUT` is sent whose `serviceGroups` is the existing groups unchanged plus `search` with the data group's compute and disk, the plan line is `+ serviceGroups[search]`, the tool waits until healthy, and capella.yaml records the group; a later `plan` reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_group_cmd_ac2_add_body` | `tests/scenario/test_cluster_group.py` | PUT body |
| `test_group_cmd_ac2_file_updated_no_drift` | same | |

### AC3 — Add is idempotent and refuses a clash
**Given** AC2 completed, **when** the same command runs again, **then** `already exists`, exit 0, zero writes. **Given** the same services with a different size, **then** exit 3 pointing to `cluster scale` / `cluster update --group`. **Given** 25 nodes, or a total over 27, or a single-node or free-tier cluster, **then** exit 3 (or 4 for free tier, as CAP-041) with the existing rule message and zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_group_cmd_ac3_add_rerun_noop` | `tests/scenario/test_cluster_group.py` | |
| `test_group_cmd_ac3_add_refused` | same | Parametrised |
| `test_group_cmd_ac3_add_refused_single_node` | same | |
| `test_group_cmd_ac3_add_refused_total_and_free_tier` | same | |

### AC4 — Remove a group with the scale-in guards
**Given** `cluster group remove nova-dev-01 search` and another group still runs search, **then** the plan shows `- serviceGroups[search]` with `checks: …`, and after confirmation one `PUT` without that group is sent and capella.yaml drops it. **Given** it is the last group running search, **then** exit 4 unless `--allow-service-removal`. **Given** the memory or replica check fails, **then** exit 4 as in CAP-016. **Given** the only data group, **then** exit 4 `the last group running data cannot be removed`.

| Test | Location | Verifies |
|---|---|---|
| `test_group_cmd_ac4_remove_body` | `tests/scenario/test_cluster_group.py` | |
| `test_group_cmd_ac4_remove_guards` | same | Last search nodes, last data group |
| `test_group_cmd_ac4_remove_memory_guard` | same | |

### AC5 — Remove of a missing group
**Given** a services set that no group has, **then** `no service group 'eventing' (groups: data · index,query · search)`, exit 0 with `--auto-approve` (nothing to remove, so re-runs are safe) and zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_group_cmd_ac5_remove_missing_noop` | `tests/scenario/test_cluster_group.py` | |

### AC6 — Only when healthy
**Given** the cluster is `turnedOff`, **then** add and remove exit 4 `turned off; power it on before scaling` (CAP-015 AC7) with zero writes and an unchanged capella.yaml.

| Test | Location | Verifies |
|---|---|---|
| `test_group_cmd_ac6_turned_off_blocked` | `tests/scenario/test_cluster_group.py` | |

### AC7 — Discoverable
**Given** `cluster group --help`, **then** every verb has an example. `help scaling` and `docs/runbook.md` use `cluster group add|remove` instead of describing a file edit, and the runbook commands are parsed in CI.

| Test | Location | Verifies |
|---|---|---|
| `test_group_cmd_ac7_help_examples` | `tests/scenario/test_cluster_group.py` | |

## Out of scope
- Changing a group's services set in place (add the new group, then remove the old one).
- Changing a group's size: `cluster scale --group` (nodes) and `cluster update --group` (compute, disk) already do it.

## Open questions
- Is a services change of a live group possible in Capella without a rebalance of both groups? If Capella supports it efficiently, a later `cluster group update --services` could replace remove + add.

## Implementation notes (as built)
- `capellactl/cli/cluster_group.py`: the `cluster group` sub-group (registered next to `cluster schedule`). `add` and `remove` change the cluster entry with the config editor and go through `change_and_apply`, so the plan, confirmation, `.bak`, restore-on-rejection and `--no-apply` behave as for every cluster command.
- `list` reads `GET …/clusters/{id}`, so it shows what Capella reports (for Azure premium disks, the size and IOPS the disk type sets).
- `add` copies compute and disk from the first group that runs data. A known-size warning (CAP-051 AC9) is shown for the new group's size. A group with the same services and the same size given (or no size given) is a no-op with exit 0; a different size exits 3 and points to `cluster scale`/`cluster update --group`.
- `remove` passes `allow_service_group_removal` itself (the command is the opt-in) and `--allow-service-removal`/`--skip-capacity-check` through to the CAP-016 checks. The last data group is refused by the command (exit 4) before validation, so the message is about removing data rather than the generic "at least one service group must run the data service".
- The schema and engine needed no change; `help scaling` and the runbook ("Add or remove a service group") describe the commands.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_group_cmd_ac1_list` (tests/scenario/test_cluster_group.py) |
| AC2 | `test_group_cmd_ac2_add_body`, `test_group_cmd_ac2_file_updated_no_drift` (tests/scenario/test_cluster_group.py) |
| AC3 | `test_group_cmd_ac3_add_rerun_noop`, `test_group_cmd_ac3_add_refused`, `test_group_cmd_ac3_add_refused_single_node`, `test_group_cmd_ac3_add_refused_total_and_free_tier` (tests/scenario/test_cluster_group.py) |
| AC4 | `test_group_cmd_ac4_remove_body`, `test_group_cmd_ac4_remove_guards`, `test_group_cmd_ac4_remove_memory_guard` (tests/scenario/test_cluster_group.py) |
| AC5 | `test_group_cmd_ac5_remove_missing_noop` (tests/scenario/test_cluster_group.py) |
| AC6 | `test_group_cmd_ac6_turned_off_blocked` (tests/scenario/test_cluster_group.py) |
| AC7 | `test_group_cmd_ac7_help_examples` (tests/scenario/test_cluster_group.py) |
