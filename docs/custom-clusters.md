# Custom clusters and service groups

This guide shows how to deploy a provisioned cluster with exactly the size and services you need, including
**multi-dimensional scaling (MDS)**: separate groups of nodes for different services, each with its own node count,
compute and disk. Everything is done with `capellactl` commands; you never edit `capella.yaml`.

You need a working setup first (a profile and a `capella.yaml`): follow [Getting started](getting-started.md) up to
step 3. Every example below uses project `sandbox`.

- [Service groups in one minute](#service-groups-in-one-minute)
- [1. See what you can choose](#1-see-what-you-can-choose)
- [2. Plan the layout](#2-plan-the-layout)
- [3. Create the cluster with one command](#3-create-the-cluster-with-one-command)
- [4. Or answer questions](#4-or-answer-questions)
- [5. How a wrong spec is caught](#5-how-a-wrong-spec-is-caught)
- [6. Copy a layout that already works](#6-copy-a-layout-that-already-works)
- [7. Change the layout later](#7-change-the-layout-later)
- [8. Single-node and advanced options](#8-single-node-and-advanced-options)
- [9. Keep capella.yaml in step with Capella](#9-keep-capellayaml-in-step-with-capella)
- [10. Choose the disk type](#10-choose-the-disk-type)
- [Troubleshooting](#troubleshooting)

## Service groups in one minute

A **service group** is a set of identical nodes that run the same Couchbase services. A small cluster has one group
that runs `data, index, query` on every node. In production you often split them, so each workload gets nodes sized
for it and can grow on its own:

| Group | Services | Typical sizing |
|---|---|---|
| Data | `data` | Memory for the buckets' working set; 3 nodes or more |
| Query and index | `index,query` | CPU for queries, memory for indexes |
| Search | `search` | CPU and disk for full-text indexes |
| Analytics | `analytics` | CPU, memory and large disks |

capellactl identifies a group by its set of services (`index,query` and `query,index` are the same group), so each
group needs a different set.

## 1. See what you can choose

```bash
capellactl cluster options
```
```
Provisioned        available
  providers        aws, gcp, azure
  sizes            dev (1 × 4 vCPU/16 GB, single node), small (3 × 4 vCPU/16 GB), medium (3 × 8 vCPU/32 GB), large (5 × 16 vCPU/64 GB), custom
  support plans    basic, developer pro, enterprise (timezones ET, GMT, IST, PT)
  services         data, index, query, search, analytics, eventing
  service groups   first group 3–27 nodes, other groups 2–24, at most 27 per cluster, one group runs data
  node sizes       vCPU/RAM GB (from Capella's documentation; config/compute.yaml)
    aws    4/16, 4/32, 8/16, 8/32, 8/64, 16/32, 16/64, 16/128, 32/64, 32/128, 32/256, 48/96, 48/192, 48/384, 64/128, 64/256, 64/512
    gcp    4/16, 4/32, 8/16, 8/32, 8/64, 16/32, 16/64, 16/128, 32/128, 32/256, 36/72, 48/96, 48/192, 48/384, 64/256, 64/512, 72/144
    azure  4/16, 4/32, 8/16, 8/32, 8/64, 16/32, 16/64, 16/128, 20/160, 32/64, 32/128, 32/256, 48/96, 48/192, 48/384, 64/128, 64/256, 64/512, 72/144
  server versions  in use by your clusters: 8.0.1
  regions          any region of the provider; in use by your clusters: aws us-east-1
```

The node sizes come from Capella's documentation for each cloud provider. Capella's API has no endpoint that lists
them per region, so a size can still be unavailable in a particular region; Capella then says so (see step 5).

## 2. Plan the layout

Capella's rules, which capellactl checks before anything is sent:

| Rule | Value |
|---|---|
| At least one group runs `data` | always |
| Nodes in the first group (capellactl puts a data group first) | 3–27 |
| Nodes in every other group | 2–24 |
| Nodes in the whole cluster | at most 27 |
| Services of a group | any of `data, index, query, search, analytics, eventing`; a different set per group |

For example, 7 nodes on Azure: data on 3 × 8 vCPU/32 GB, index and query on 2 × 8/32, search on 2 × 4/16.

## 3. Create the cluster with one command

Give one `--group` per service group:

```bash
capellactl cluster create prod-01 --project sandbox --provider azure --region eastus \
  --group data:3x8/32 \
  --group index,query:2x8/32 \
  --group search:2x4/16
```
```
New cluster prod-01 in project sandbox: azure eastus, 3 groups · 7 nodes (data 3 × 8/32 · index,query 2 × 8/32 · search 2 × 4/16), network 10.0.0.0/24, support developer pro
Project sandbox · organization org-1

  + cluster prod-01  azure eastus · multi-AZ · 3 service groups · 7 nodes · developer pro
      + serviceGroups[data]         3 × 8 vCPU/32 GB P6
      + serviceGroups[index,query]  2 × 8 vCPU/32 GB P6
      + serviceGroups[search]       2 × 4 vCPU/16 GB P6

Plan: 1 to add, 0 to change, 0 to delete, 0 blocked.
Add prod-01 to capella.yaml and deploy it now? [y/N]: y
→ creating cluster prod-01 …
  cluster prod-01: deploying (0s) ...................
  cluster prod-01: healthy (11m02s)
connectionString (prod-01): couchbases://cb.xxxx.cloud.couchbase.com
Apply complete in 11m03s.
```

Each `--group` is `SERVICES:NODESxCPU/RAM[:DISK]`:

| Part | Meaning | Example |
|---|---|---|
| `SERVICES` | Comma-separated services | `index,query` |
| `NODESxCPU/RAM` | Nodes, vCPUs per node, GB of RAM per node (read it like the plan line `2 × 8 vCPU/32 GB`) | `2x8/32` |
| `DISK` (optional) | `type=`, `size=` (GB per node), `iops=` (AWS), `auto-expansion=true` (Azure), comma-separated | `size=200,iops=5000` |

Without `DISK`, each group gets the provider's default disk: AWS `gp3` 50 GB 3000 IOPS, Google Cloud `pd-ssd` 50 GB,
Azure `P6`. `--disk-type`, `--disk-size` and `--disk-iops` set the default for every group that does not name its own:

```bash
capellactl cluster create prod-02 --project sandbox --provider aws --region us-east-1 --disk-size 100 \
  --group data,index,query:3x8/32 \
  --group analytics:2x16/64:size=200,iops=5000
```

Other options work as for any cluster: `--region`, `--cidr`, `--availability`, `--support-plan`,
`--support-timezone`, `--description`. To record the cluster without deploying it yet, add `--no-apply` and run
`capellactl apply` later. `--group` replaces `--size`, `--nodes`, `--cpu`, `--ram` and `--services`, which set a
single group.

## 4. Or answer questions

Run `cluster create` with no size options, choose `custom`, then `multiple groups`. Each group is asked in turn, the
node size is picked from the list of sizes Capella offers, and every answer is checked as you give it:

```bash
capellactl cluster create prod-03 --project sandbox
```
```
Cluster type (free, provisioned) [provisioned]:
Cloud provider (aws, gcp, azure) [aws]: azure
Size (dev, small, medium, large, custom) [small]: custom
Service layout (one group, multiple groups) [one group]: multiple groups
Service group 1
  Services [data,index,query,search,analytics,eventing]: data
  Nodes (3–27) [3]:
  Node size (vCPU / RAM GB):
     1) 4/16   2) 4/32   3) 8/16   4) 8/32   5) 8/64   6) 16/32
     7) 16/64   8) 16/128   9) 20/160  10) 32/64  11) 32/128  12) 32/256
    13) 48/96  14) 48/192  15) 48/384  16) 64/128  17) 64/256  18) 64/512
    19) 72/144
    20) other
  Choose [1]: 4
Add another service group? [y/N]: y
Service group 2  (nodes so far: 3 of 27)
  Services [index,query,search,analytics,eventing]: index,query
  Nodes (2–24) [2]:
  Node size (vCPU / RAM GB):
     …
  Choose [1]: 4
Add another service group? [y/N]: n
Region [eastus]:
Network CIDR (must not overlap other clusters) [10.0.2.0/24]:
Support plan (basic, developer pro, enterprise) [developer pro]:
New cluster prod-03 in project sandbox: azure eastus, 2 groups · 5 nodes (data 3 × 8/32 · index,query 2 × 8/32), network 10.0.2.0/24, support developer pro

  + cluster prod-03  azure eastus · multi-AZ · 2 service groups · 5 nodes · developer pro
      + serviceGroups[data]         3 × 8 vCPU/32 GB P6
      + serviceGroups[index,query]  2 × 8 vCPU/32 GB P6

Add prod-03 to capella.yaml and deploy it now? [y/N]: y
```

The default is the services no group runs yet (every service for the first group): press Enter to put all of
them in this group, or type the ones you want. A wrong answer (an unknown service, a set of services another group already runs, too many nodes) is explained and
only that question is asked again. `one group` keeps the short questions: nodes, vCPUs, RAM.

## 5. How a wrong spec is caught

Capella's API has no "check only" call, so capellactl stops mistakes in layers, as early as it can. None of them
leaves a half-built cluster or a `capella.yaml` that disagrees with Capella.

| What is wrong | Caught by | What you see |
|---|---|---|
| A typo in the spec | capellactl, before anything is sent | `--group dat:3x8/32: unknown service 'dat'; did you mean data?` or `--group data:3x8: expected NODESxCPU/RAM, e.g. 3x8/32 (got '3x8')`; exit 3 |
| A rule from step 2 | capellactl, before anything is sent | `serviceGroups[0].numOfNodes: must be between 3 and 27`, `two groups run index,query; …`; exit 3 |
| A size not in Capella's list | capellactl, in the plan | `! serviceGroups[data]: 8 vCPU/30 GB is not a known aws size; Capella may reject it` before the `[y/N]` question; answer `n` to fix it |
| Anything else you did not mean | you, in the plan | every group with its disk, before you confirm |
| A size Capella does not offer in that region | Capella, when the cluster is created | Capella's message and hint; nothing is created and `capella.yaml` is put back as it was. Fix the value and run the same command again |

In the rare case that Capella accepts the cluster and the deployment fails later, the cluster stays in
`deploymentFailed`: capellactl never deletes it on its own. Delete it with `capellactl cluster delete NAME` and run the
create again.

## 6. Copy a layout that already works

To repeat the layout of a cluster you already have, including one created in the Capella UI, clone it. The source is
read live from Capella:

```bash
capellactl cluster clone prod-01 prod-01-weu --region westeurope --no-data-model    # layout only, another region
capellactl cluster clone prod-01 prod-01-copy --region eastus --no-data-model       # same region: asks first
```

Without `--no-data-model` the buckets, scopes and collections are copied too (never the documents).

## 7. Change the layout later

See the groups of a cluster as Capella reports them:

```bash
capellactl cluster group list prod-01
```
```
S.NO  SERVICES          NODES  vCPU  RAM GB  DISK
1     data              3      8     32      P6 64 GB 240 IOPS
2     index,query       2      8     32      P6 64 GB 240 IOPS
3     search            2      4     16      P6 64 GB 240 IOPS
total nodes: 7 of 27
```

| To … | Run |
|---|---|
| Add a group (sizes default to the data group's) | `capellactl cluster group add prod-01 --services eventing --nodes 2` |
| Add a group with its own size | `capellactl cluster group add prod-01 --services analytics --nodes 2 --cpu 16 --ram 64` |
| Add or remove nodes in a group | `capellactl cluster scale prod-01 --group index,query --nodes 3` |
| Give a group bigger nodes or disks | `capellactl cluster update prod-01 --group search --cpu 8 --ram 32` |
| Remove a group | `capellactl cluster group remove prod-01 eventing` |
| Change a group's services | add the new group, then remove the old one |

```bash
capellactl cluster group add prod-01 --services eventing --nodes 2
```
```
  ~ cluster prod-01   scale out
    + serviceGroups[eventing]  2 × 8 vCPU/32 GB P6

Add service group eventing to prod-01 and record it in capella.yaml? [y/N]: y
```

Removing a group runs the same safety checks as any scale-in: the buckets must still fit in memory, and replicas need
enough data nodes. Removing the last group that runs a service needs `--allow-service-removal`, and the last data
group is never removed:

```bash
capellactl cluster group remove prod-01 search
```
```
  ! cluster prod-01  removing serviceGroups[search] removes the last search nodes; pass --allow-service-removal
    - serviceGroups[search]  2 × 4 vCPU/16 GB P6

Nothing was written to capella.yaml or changed in Capella.
```

Adding a group that already exists with the same size does nothing (exit 0), so scripts can run it again.

## 8. Single-node and advanced options

A single node of any size, for development:

```bash
capellactl cluster create dev-03 --project sandbox --single-node --cpu 8 --ram 32
```

Options that are never asked, only given on the command line (`capellactl cluster create --help` lists them under
*Advanced options*). They cannot be changed after the cluster is created:

| Option | Sets |
|---|---|
| `--single-node` | one node; `--cpu`/`--ram` choose its size (default 4/16); services from `data, index, query, search` |
| `--server-version 8.0` | the Couchbase Server version (default: Capella's) |
| `--availability single --zone ZONE` | the availability zone of a single-AZ cluster |
| `--cmek-id ID` | an existing customer-managed encryption key |
| `--private-dns` | private DNS resolution |
| `--disk-auto-expansion` | Azure: disks grow automatically (can be changed later with `cluster update`) |

```bash
capellactl cluster create prod-04 --project sandbox --provider azure --region eastus \
  --group data:3x8/32 --group index,query:2x8/32 --server-version 8.0 --disk-auto-expansion
```

## 9. Keep capella.yaml in step with Capella

`capellactl sync` brings `capella.yaml` in line with everything your organization has in Capella: it refreshes the
projects in the file and adds the ones that are missing, including clusters someone created in the Capella UI.

```bash
capellactl sync                          # every project
capellactl sync --project sandbox        # only this project
capellactl sync --skip-project non-prod  # leave a project out, now and on later syncs
capellactl sync --dry-run                # CI: exit 2 when capella.yaml is out of date
```

Clusters that are turned off do not hold `sync` up. Their size and service groups are recorded at once; their buckets
and credentials, which Capella does not return while a cluster is off, are kept from `capella.yaml` (or read for the
first time) on the next `sync` after the cluster is on again:

```
added project non-prod (5 clusters)
3 clusters are turned off: RMPRCCBETST, RMPRCCBWTST, ct-n-zweus-mktfareevl-stg
  not read yet: buckets and credentials of RMPRCCBETST, RMPRCCBWTST, ct-n-zweus-mktfareevl-stg — run 'capellactl sync' again when they are on
capella.yaml updated from Capella (previous version kept as capella.yaml.bak).
```

## 10. Choose the disk type

Each service group has its own disk. You choose its type the way you choose vCPU and RAM; the type decides how large
and how fast the disk can be:

```bash
capellactl cluster disk-types --provider aws
```
```
S.NO  PROVIDER  TYPE  SIZE (GB)  IOPS        FOR
1     aws       gp3   50–16000   3000–16000  general-purpose SSD (default)
2     aws       io2   50–16000   3000–64000  provisioned-IOPS SSD for latency-sensitive, write-heavy workloads; costs more
```

| Provider | Type | Size per node | Speed (IOPS) |
|---|---|---|---|
| AWS | `gp3` (default) | 50 GB – 16 TB | 3,000 – 16,000, set on its own |
| AWS | `io2` | 50 GB – 16 TB | 3,000 – 64,000 |
| Google Cloud | `pd-ssd` (only type) | 50 GB and up | follows the size: 60 per GB (50 GB → 1,500 read + 1,500 write) |
| Azure | `P6` `P10` `P15` `P20` `P30` `P40` `P50` `P60` | fixed by the type: 64, 128, 256, 512, 1,024, 2,048, 4,096, 8,192 GiB | fixed: 240, 500, 1,100, 2,300, 5,000, 7,500, 7,500, 16,000 |
| Azure | `Ultra` (regions that offer it) | 64, 128, 256, 512 GiB, 1–15 TiB | set by you, up to 19,200 (64 GiB) … 80,000 (512 GiB+) |

When you don't give `--disk-iops`, capellactl uses Capella's recommended IOPS for the disk size (for gp3 and io2:
3,000 up to 99 GB, 4,370 for 100–199 GB, … 16,000 from 1,000 GB). A higher value is allowed.

```bash
capellactl cluster create prod-05 --provider aws --region us-east-1 --size medium --disk-type gp3 --disk-size 200
capellactl cluster group add prod-05 --services search --nodes 2 --disk-type io2 --disk-size 200
capellactl cluster update prod-05 --group data,index,query --disk-type io2 --disk-iops 20000
```

Answering questions instead (`capellactl cluster create prod-05`, size `custom`), the disk type is asked right after
the node size, with the same table, and then only what that type lets you set: the size (with its range) and the
IOPS (with the recommendation for that size). `cluster group add` asks the same, starting from the data group's disk.
Changing the disk type of a running cluster replaces and rebalances the group's nodes, except an in-place change on
AWS (at most once every 6 hours); the plan says so before you confirm.

## Troubleshooting

| Message | What to do |
|---|---|
| `--group sets nodes, size and services per group; remove --nodes` | Use either `--group` (several groups) or `--size`/`--nodes`/`--cpu`/`--ram`/`--services` (one group), not both |
| `two groups run index,query; each group needs a different set of services` | Merge the two groups, or give them different services |
| `a cluster can have at most 27 nodes (declared 28)` | Reduce the node counts; the limit is for the whole cluster |
| `autoExpansion is for azure disks only` | Remove `auto-expansion=` or `--disk-auto-expansion` on AWS and Google Cloud |
| `! … is not a known aws size; Capella may reject it` | Pick a size from `capellactl cluster options`, or confirm if you know Capella offers it |
| Capella's message after `Add … and deploy it now?`, then `capella.yaml was restored` | Capella refused the cluster; nothing was created. Fix the value it names and run the same command |
| `group search exists with 2 × 4/16; use 'capellactl cluster scale …'` | The group exists with another size: change it with `cluster scale --group` or `cluster update --group` |
| `the last group running data cannot be removed` | Every cluster needs a data group; add another data group first if you want to replace it |
