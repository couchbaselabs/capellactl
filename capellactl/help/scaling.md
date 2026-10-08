# Scaling

Scaling changes `serviceGroups` and is sent as one cluster update; capellactl waits until the
cluster is healthy again.

- **Scale out**: `capellactl cluster scale NAME --nodes N [--group SERVICES]`.
- **Scale up**: `capellactl cluster update NAME --cpu 8 --ram 32` or `--disk-size 100 [--disk-iops …]`.
- **Scale in / down**: fewer nodes, less RAM or a removed group. Capacity checks run first and the plan
  shows them (`checks: memory ok … · replicas ok …`). Refused when the buckets' memory would not fit,
  when a bucket's replicas would lack data nodes, or when the last data group would go. Removing the
  last nodes of another service needs `--allow-service-removal`; removing a whole group also needs
  `--allow-service-group-removal`. If cluster stats cannot be read: `--skip-capacity-check`.
- **Disk size** cannot be reduced.

**Limits**: first service group 3–27 nodes; additional groups 2–24; at most 27 nodes per cluster;
`singleNode` clusters have exactly 1 node and cannot be scaled.

Groups are matched by their set of services (`data,index,query`), so order in the file does not matter.

One node at a time from scripts or alerts: `capellactl cluster scale NAME --step +1 --max 6` or
`--step -1 --min 3` (exits 0 at the limit; `--all-groups` steps each group; `-o json` for automation).
