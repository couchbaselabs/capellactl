# Scaling

Scaling changes `serviceGroups` and is sent as one cluster update; capellactl waits until the
cluster is healthy again.

- **Create with several service groups** (multi-dimensional scaling): one `--group SERVICES:NODESxCPU/RAM[:DISK]`
  per group, e.g. `capellactl cluster create NAME --group data:3x8/32 --group index,query:2x8/32 --group search:2x4/16`.
  Sizes Capella offers: `capellactl cluster options`. Copy an existing layout: `cluster clone … --no-data-model`.
- **Add or remove a service group**: `capellactl cluster group add NAME --services search --nodes 2`,
  `capellactl cluster group remove NAME search`; see them with `capellactl cluster group list NAME`.
- **Scale out**: `capellactl cluster scale NAME --nodes N [--group SERVICES]`.
- **Scale up**: `capellactl cluster update NAME --cpu 8 --ram 32` or `--disk-size 100 [--disk-iops …]`.
- **Scale in / down**: fewer nodes, less RAM or a removed group. Capacity checks run first and the plan
  shows them (`checks: memory ok … · replicas ok …`). Refused when the buckets' memory would not fit,
  when a bucket's replicas would lack data nodes, or when the last data group would go. Removing the
  last nodes of another service needs `--allow-service-removal`; removing a whole group also needs
  `--allow-service-group-removal`. If cluster stats cannot be read: `--skip-capacity-check`.
- **Disk size** cannot be reduced.

**Disk types**: each service group has its own disk; `capellactl cluster disk-types [--provider P]` lists the
types with their size range, speed and use. AWS: `gp3` (general purpose, default) or `io2` (provisioned IOPS, up to
64000). Google Cloud: `pd-ssd` only, 60 IOPS per GB, so a larger disk is a faster one. Azure: `P6`…`P60` (size and
speed set by the type) or `Ultra` (size and IOPS chosen). Choose with `--disk-type` on `cluster create`, `cluster
group add` and `cluster update NAME --group SERVICES --disk-type io2`; interactive commands offer the list. Without
`--disk-iops`, capellactl uses Capella's recommended IOPS for the disk size. Changing a disk type replaces and
rebalances the group's nodes, except an in-place change on AWS (at most once every 6 hours).

**Limits**: first service group 3–27 nodes; additional groups 2–24; at most 27 nodes per cluster;
`singleNode` clusters have exactly 1 node and cannot be scaled.

Groups are matched by their set of services (`data,index,query`), so order in the file does not matter.

One node at a time from scripts or alerts: `capellactl cluster scale NAME --step +1 --max 6` or
`--step -1 --min 3` (exits 0 at the limit; `--all-groups` steps each group; `-o json` for automation).
