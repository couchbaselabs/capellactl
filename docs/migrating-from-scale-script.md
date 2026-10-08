# Migrating from `scale_capella_cluster.sh` to `capellactl cluster scale`

The Nova `scale_capella_cluster.sh` script adds or removes one node with `--scale-up` / `--scale-down`, within `MIN_NODE_COUNT` (3) and `MAX_NODE_COUNT` (6). `capellactl cluster scale --step` does the same and keeps `capella.yaml` in step.

## Flag by flag

| Script | capellactl |
|---|---|
| `scale_capella_cluster.sh --scale-up` | `capellactl --auto-approve cluster scale CLUSTER --step +1 --max 6` |
| `scale_capella_cluster.sh --scale-down` | `capellactl --auto-approve cluster scale CLUSTER --step -1 --min 3` |
| `MIN_NODE_COUNT=3` | `--min 3` (default: 3 for the first service group, 2 for the others) |
| `MAX_NODE_COUNT=6` | `--max 6` (default: 27 for the first group, 24 for the others) |
| exit 0 with a message at the limit | the same: `already at maximum (6)` / `already at minimum (3)`, exit 0, nothing changed |
| `grep '"error"'` on the response | exit codes: 0 done or at the limit, 4 blocked (for example a capacity check), 1 API error, 5 timed out |
| `BEARER_TOKEN`, `ORG_ID` | `capellactl configure` once, or `CAPELLA_API_KEY` and `CAPELLA_ORG_ID` in CI |

```bash
capellactl --auto-approve cluster scale nova-dev-01 --step +1 --max 6
capellactl --auto-approve cluster scale nova-dev-01 --step -1 --min 3
capellactl --auto-approve cluster scale nova-dev-01 --step +1 --group search --max 4
capellactl --auto-approve cluster scale nova-dev-01 --step +1 --all-groups
capellactl --auto-approve -o json cluster scale nova-dev-01 --step +1 --max 6
```

## What is different

- **Per group, not a sum.** The script added up `numOfNodes` over every service group and set *every* group to that total ± 1, so a cluster with `data,index,query` = 3 and `search` = 2 became 6 and 6. capellactl changes one group (the one running `data`, or `--group SERVICES`) by one node; `--all-groups` steps each group by one on its own (3 → 4 and 2 → 3).
- **Scale-down is checked.** Before removing a node capellactl checks that the buckets still fit in memory and that every bucket's replicas still have enough data nodes (CAP-016); otherwise it exits 4 and changes nothing.
- **Waits for a running change.** When the cluster is already scaling, the step is computed from the count after that change (with `--no-wait` it exits 4 instead).
- **capella.yaml stays the record.** The new node count is written to `capella.yaml`, so a later `capellactl apply` keeps it.
- **Machine-readable output.** `-o json` prints `{"cluster", "group", "from", "to", "status": "scaled|at_limit|blocked"}` (an array with `--all-groups`).
