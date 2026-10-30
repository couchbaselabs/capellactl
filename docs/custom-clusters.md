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
- [4. Choose each group's disk](#4-choose-each-groups-disk)
- [5. Or answer questions](#5-or-answer-questions)
- [6. How a wrong spec is caught](#6-how-a-wrong-spec-is-caught)
- [7. Copy a layout that already works](#7-copy-a-layout-that-already-works)
- [8. Change the layout later](#8-change-the-layout-later)
- [9. Single-node and advanced options](#9-single-node-and-advanced-options)
- [10. Keep capella.yaml in step with Capella](#10-keep-capellayaml-in-step-with-capella)
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

capellactl identifies a group by its set of services. `index,query` and `query,index` name the same group, so each
group needs a different set. You use that name later to pick the group to change (step 8).

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
them per region, so a size can still be unavailable in a particular region; Capella then says so (see step 6).

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

Give one `--group` per service group. With `--cidr` and `--support-plan` as well, nothing is asked except the
final `[y/N]` (`-y` answers that too); the options are explained after the example:

```bash
capellactl cluster create prod-01 --project sandbox --provider azure --region eastus \
  --cidr 10.0.0.0/24 --support-plan "developer pro" \
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

### The parts of `--group`

Each `--group` is `SERVICES:NODESxCPU/RAM[:DISK]`. Take `index,query:2x8/32` from the example:

| Part | Example | Meaning |
|---|---|---|
| `SERVICES` | `index,query` | The services every node of the group runs, comma-separated. The set is also the group's name. |
| `NODES` | `2` | How many nodes the group has. The limits are in step 2. |
| `CPU/RAM` | `8/32` | The size of each node: vCPUs and GB of RAM. Use a pair from `cluster options` (step 1). The plan shows it as `2 × 8 vCPU/32 GB`. |
| `DISK` | *(not given)* | Optional. The disk of each node in the group. Without it the group gets the default disk; see step 4. |

`--group` describes a whole group, so it cannot be combined with `--size`, `--nodes`, `--cpu`, `--ram` or
`--services`. Those options describe a cluster with only one group.

### Options for the whole cluster

These options apply to the cluster itself, not to a group. Without them, capellactl uses the default shown:

| Option | Default | Meaning |
|---|---|---|
| `--project` | asked when there is more than one | The project in `capella.yaml` the cluster belongs to |
| `--provider` | `aws` | Cloud provider: `aws`, `gcp` or `azure` |
| `--region` | `us-east-1`, `us-east1` or `eastus` | Region of that provider |
| `--cidr` | a free `/24` | The cluster's private network. A range that overlaps another cluster of the project, in capella.yaml or only in Capella, is refused before anything is created; an overlap with another project's cluster is a warning |
| `--availability` | `multi` | `multi` spreads nodes across availability zones; `single` keeps them in one |
| `--support-plan` | `developer pro` | `basic`, `developer pro` or `enterprise` |
| `--support-timezone` | `PT` | `ET`, `GMT`, `IST` or `PT` |
| `--description` | none | Free text shown in Capella |
| `--no-apply` | off | Record the cluster in `capella.yaml` without deploying it; run `capellactl apply` later |

## 4. Choose each group's disk

Every node in a group has its own disk, and all disks in a group are the same. The **disk type** decides which
other values you can set and their range:

| Provider | Type | Size per node | Speed (IOPS) |
|---|---|---|---|
| AWS | `gp3` (default) | 50 GB – 16 TB | 3,000 – 16,000, set separately from the size |
| AWS | `io2` | 50 GB – 16 TB | 3,000 – 64,000 |
| Google Cloud | `pd-ssd` (only type) | 50 GB and up | follows the size: 60 per GB (50 GB → 1,500 read + 1,500 write) |
| Azure | `P6` (default) `P10` `P15` `P20` `P30` `P40` `P50` `P60` | fixed by the type: 64, 128, 256, 512, 1,024, 2,048, 4,096, 8,192 GiB | fixed by the type: 240, 500, 1,100, 2,300, 5,000, 7,500, 7,500, 16,000 |
| Azure | `Ultra` (only in regions that offer it, such as `eastus`) | 64, 128, 256, 512 GiB, 1–15 TiB | set by you, up to 19,200 (64 GiB) … 80,000 (512 GiB and up) |

`capellactl cluster disk-types --provider PROVIDER` prints the same list, with what each type is for:

```bash
capellactl cluster disk-types --provider aws
```
```
S.NO  PROVIDER  TYPE  SIZE (GB)  IOPS        FOR
1     aws       gp3   50–16000   3000–16000  general-purpose SSD (default)
2     aws       io2   50–16000   3000–64000  provisioned-IOPS SSD for latency-sensitive, write-heavy workloads; costs more
```

### The disk values

Each value can be given for one group (inside `--group`, after the second `:`) or for every group (an option of
`cluster create`):

| In `--group` | For every group | Meaning | Where it applies |
|---|---|---|---|
| `type=` | `--disk-type` | The disk type from the table above | All providers |
| `size=` | `--disk-size` | GB per node | AWS, Google Cloud, Azure `Ultra`. An Azure `P` type's size comes with the type, so a size has no effect on it |
| `iops=` | `--disk-iops` | Speed in IOPS | AWS, Azure `Ultra`. Without it, capellactl uses Capella's recommendation for the size (gp3 and io2: 3,000 up to 99 GB, 4,370 for 100–199 GB, … 16,000 from 1,000 GB); a higher value is allowed. Not for Google Cloud, where the size sets the speed |
| `auto-expansion=` | `--disk-auto-expansion` | `true`: Azure grows the disk when it fills up | Azure only |

Inside `--group`, separate the values with commas, for example `data:3x8/32:type=io2,size=200,iops=8000`.

### Which value a group gets

capellactl works out each disk value separately for each group, and uses the first one it finds:

1. the value in that group's `--group` (`type=`, `size=`, `iops=`, `auto-expansion=`)
2. the matching `--disk-*` option, which applies to every group that does not set the value itself
3. the default: the provider's default type, the smallest size that type allows (50 GB on AWS and Google Cloud),
   and the recommended IOPS for that size

Because each value is worked out separately, a group that sets only `type=` still takes `--disk-size` and
`--disk-iops` from the command line.

On AWS:

```bash
capellactl cluster create prod-02 --project sandbox --provider aws --region us-east-1 \
  --cidr 10.0.1.0/24 --support-plan "developer pro" --disk-size 100 \
  --group data,index,query:3x8/32 \
  --group analytics:2x16/64:size=200,iops=5000
```

| Group | Type | Size | IOPS |
|---|---|---|---|
| `data,index,query` | `gp3`, default | 100 GB, from `--disk-size` | 4,370, recommended for 100 GB |
| `analytics` | `gp3`, default | 200 GB, from `size=` | 5,000, from `iops=` |

On Azure, you choose a `P` disk's size by choosing its type, because the type sets both size and speed. Only
`Ultra` takes a size and IOPS:

```bash
capellactl cluster create prod-06 --project sandbox --provider azure --region eastus \
  --cidr 10.0.2.0/24 --support-plan "developer pro" --disk-type P10 \
  --group data,index,query:3x8/32 \
  --group search:2x8/32:type=P20 \
  --group analytics:2x16/64:type=Ultra,size=256,iops=20000
```
```
  + cluster prod-06  azure eastus · multi-AZ · 3 service groups · 7 nodes · developer pro
      + serviceGroups[data,index,query]  3 × 8 vCPU/32 GB P10
      + serviceGroups[search]            2 × 8 vCPU/32 GB P20
      + serviceGroups[analytics]         2 × 16 vCPU/64 GB Ultra 256 GB
```

| Group | Type | Size | IOPS |
|---|---|---|---|
| `data,index,query` | `P10`, from `--disk-type` | 128 GiB, set by `P10` | 500, set by `P10` |
| `search` | `P20`, from `type=` (overrides `--disk-type`) | 512 GiB, set by `P20` | 2,300, set by `P20` |
| `analytics` | `Ultra`, from `type=` (overrides `--disk-type`) | 256 GiB, from `size=` | 20,000, from `iops=` |

With a single group (`--size` or `--nodes`/`--cpu`/`--ram`), the `--disk-*` options set that one group's disk:

```bash
capellactl cluster create prod-05 --project sandbox --provider aws --region us-east-1 \
  --cidr 10.0.3.0/24 --support-plan "developer pro" --size medium --disk-type gp3 --disk-size 200
```

To change the disk of a cluster that already exists, see step 8.

## 5. Or answer questions

Run `cluster create` with no size options, choose `custom`, then `multiple groups`. capellactl asks about each group
in turn and checks every answer as you give it:

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
  Disk type:
    …
  Choose [1]:
Add another service group? [y/N]: y
Service group 2  (nodes so far: 3 of 27)
  Services [index,query,search,analytics,eventing]: index,query
  Nodes (2–24) [2]:
  Node size (vCPU / RAM GB):
     …
  Choose [1]: 4
  Disk type:
    …
  Choose [1]:
Add another service group? [y/N]: n
Region [eastus]:
Network CIDR (must not overlap other clusters) [10.0.4.0/24]:
Support plan (basic, developer pro, enterprise) [developer pro]:
New cluster prod-03 in project sandbox: azure eastus, 2 groups · 5 nodes (data 3 × 8/32 · index,query 2 × 8/32), network 10.0.4.0/24, support developer pro

  + cluster prod-03  azure eastus · multi-AZ · 2 service groups · 5 nodes · developer pro
      + serviceGroups[data]         3 × 8 vCPU/32 GB P6
      + serviceGroups[index,query]  2 × 8 vCPU/32 GB P6

Add prod-03 to capella.yaml and deploy it now? [y/N]: y
```

What each question means:

- **Cluster type** is only asked while your organization has no free-tier cluster.
- **Services** offers the services no group runs yet (every service for the first group). Press Enter to put all
  of them in this group, or type the ones you want.
- **Node size** lists the sizes Capella offers for the provider; `other` lets you type any vCPU and RAM.
- **Disk type** shows the table from step 4, then asks only for what that type lets you set: the size (with its
  range) and the IOPS (with the recommendation for that size).

A wrong answer, such as an unknown service, services another group already runs, or too many nodes, is explained,
and only that question is asked again. Choosing `one group` asks just for nodes, vCPUs and RAM.

## 6. How a wrong spec is caught

Capella's API has no "check only" call, so capellactl stops mistakes in layers, as early as it can. None of them
leaves a half-built cluster or a `capella.yaml` that disagrees with Capella.

| What is wrong | Caught by | What you see |
|---|---|---|
| A typo in the spec | capellactl, before anything is sent | `--group dat:3x8/32: unknown service 'dat'; did you mean data?` or `--group data:3x8: expected NODESxCPU/RAM, e.g. 3x8/32 (got '3x8')`; exit 3 |
| A rule from step 2 | capellactl, before anything is sent | `cluster prod-01 › service group data › numOfNodes` with `must be between 3 and 27`, or `two groups run index,query; …`; exit 3 |
| A size not in Capella's list | capellactl, in the plan | `! serviceGroups[data]: 8 vCPU/30 GB is not a known aws size; Capella may reject it` before the `[y/N]` question; answer `n` to fix it |
| Anything else you did not mean | you, in the plan | every group with its disk, before you confirm |
| A size Capella does not offer in that region | Capella, when the cluster is created | Capella's message and hint; nothing is created and `capella.yaml` is put back as it was. Fix the value and run the same command again |

In the rare case that Capella accepts the cluster and the deployment fails later, the cluster stays in
`deploymentFailed`: capellactl never deletes it on its own. Delete it with `capellactl cluster delete NAME` and run the
create again.

## 7. Copy a layout that already works

To repeat the layout of a cluster you already have, including one created in the Capella UI, clone it. capellactl
reads the source cluster from Capella at the time you run the command:

```bash
capellactl cluster clone prod-01 prod-01-weu --region westeurope --no-data-model    # layout only, another region
capellactl cluster clone prod-01 prod-01-copy --region eastus --no-data-model       # same region: asks first
```

Without `--no-data-model` the buckets, scopes and collections are copied too (never the documents).

## 8. Change the layout later

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

### Which group a command changes

| To … | Run | Group it changes |
|---|---|---|
| Add a group | `capellactl cluster group add prod-01 --services eventing --nodes 2` | a new group, `eventing` |
| Add or remove nodes | `capellactl cluster scale prod-01 --group index,query --nodes 3` | the group named by `--group` |
| Give a group bigger nodes or disks | `capellactl cluster update prod-01 --group search --cpu 8 --ram 32` | the group named by `--group` |
| Remove a group | `capellactl cluster group remove prod-01 eventing` | the group named |
| Change a group's services | add the new group, then remove the old one | — |

Without `--group`, `cluster scale` and `cluster update` change the group that runs `data`. If more than one group
runs `data`, they ask you to pass `--group`.

### Add a group

`cluster group add` copies the vCPU, RAM and disk of the data group. Options change only what they name:

- `--cpu` and `--ram` replace the copied node size.
- `--disk-size` and `--disk-iops` change only that value of the copied disk.
- `--disk-type` starts a new disk of that type instead of copying one. Its size and IOPS then come from
  `--disk-size` and `--disk-iops`, or from the defaults in step 4.

```bash
capellactl cluster group add prod-01 --services eventing --nodes 2
```
```
  ~ cluster prod-01   scale out
    + serviceGroups[eventing]  2 × 8 vCPU/32 GB P6

Add service group eventing to prod-01 and record it in capella.yaml? [y/N]: y
```

Adding a group that already exists with the same size does nothing (exit 0), so scripts can run it again.

### Change a group's disk

`cluster update --group` changes only the disk values you give it; the others stay as they are. For example,
`prod-05` from step 4 gets a search group with a new `io2` disk, then its first group moves to `io2` at a higher
speed:

```bash
capellactl cluster group add prod-05 --services search --nodes 2 --disk-type io2 --disk-size 200
capellactl cluster update prod-05 --group data,index,query --disk-type io2 --disk-iops 20000
```

On an Azure `P` type, `cluster update` refuses `--disk-size` and `--disk-iops`; change the type instead. Changing the
disk type of a running cluster replaces and rebalances the group's nodes, except an in-place change on AWS (at most
once every 6 hours). The plan says which one will happen before you confirm.

### Remove a group

Removing a group runs the same safety checks as any scale-in: the buckets must still fit in memory, and replicas need
enough data nodes. Removing the last group that runs a service needs `--allow-service-removal`, and the last data
group is never removed:

```bash
capellactl cluster group remove prod-01 search
```
```
  ! cluster prod-01  removing serviceGroups[search] removes the last search nodes; pass --allow-service-removal
    - serviceGroups[search]  2 × 4 vCPU/16 GB P6

[ERROR]: Nothing was written to capella.yaml or changed in Capella: the plan above has blocked changes (!)
[ACTION]: Resolve each change marked ! (its note says how), then run the command again. See 'capellactl help scaling'.
```

## 9. Single-node and advanced options

A single node of any size, for development:

```bash
capellactl cluster create dev-03 --project sandbox --single-node --cpu 8 --ram 32
```

Some options are never asked, only given on the command line (`capellactl cluster create --help` lists them under
*Advanced options*). They cannot be changed after the cluster is created:

| Option | Sets |
|---|---|
| `--single-node` | one node; `--cpu`/`--ram` choose its size (default 4/16); services from `data, index, query, search` |
| `--server-version 8.0` | the Couchbase Server version (default: Capella's) |
| `--availability single --zone ZONE` | the availability zone of a single-AZ cluster |
| `--cmek-id ID` | an existing customer-managed encryption key |
| `--private-dns` | private DNS resolution |

```bash
capellactl cluster create prod-04 --project sandbox --provider azure --region eastus \
  --cidr 10.0.8.0/24 --support-plan "developer pro" \
  --group data:3x8/32 --group index,query:2x8/32 --server-version 8.0
```

## 10. Keep capella.yaml in step with Capella

`capellactl sync` brings `capella.yaml` in line with everything your organization has in Capella: it refreshes the
projects in the file and adds the ones that are missing, including clusters someone created in the Capella UI.

```bash
capellactl sync                          # every project
capellactl sync --project sandbox        # only this project
capellactl sync --skip-project non-prod  # leave a project out, now and on later syncs
capellactl sync --dry-run                # CI: exit 2 when capella.yaml is out of date
```

Clusters that are turned off do not hold `sync` up. Their size and service groups are recorded at once. Capella does
not return their buckets and credentials while they are off, so `capella.yaml` keeps the ones it had, and the next
`sync` after the cluster is on again reads them:

```
added project non-prod (5 clusters)
3 clusters are turned off: RMPRCCBETST, RMPRCCBWTST, ct-n-zweus-mktfareevl-stg
  not read yet: buckets and credentials of RMPRCCBETST, RMPRCCBWTST, ct-n-zweus-mktfareevl-stg — run 'capellactl sync' again when they are on
capella.yaml updated from Capella (previous version kept as capella.yaml.bak).
```

## Troubleshooting

| Message | What to do |
|---|---|
| `--group sets nodes, size and services per group, so --nodes cannot be given with it` | Use either `--group` (several groups) or `--size`/`--nodes`/`--cpu`/`--ram`/`--services` (one group), not both |
| `two groups run index,query; each group needs a different set of services` | Merge the two groups, or give them different services |
| `a cluster can have at most 27 nodes (declared 28)` | Reduce the node counts; the limit is for the whole cluster |
| `autoExpansion is for azure disks only` | Remove `auto-expansion=` or `--disk-auto-expansion` on AWS and Google Cloud |
| `… uses Azure disk type P6, whose size and IOPS are set by the type` | Choose a larger `P` type, or `Ultra`, with `--disk-type` |
| `! … is not a known aws size; Capella may reject it` | Pick a size from `capellactl cluster options`, or confirm if you know Capella offers it |
| Capella's message after `Add … and deploy it now?`, then `capella.yaml was restored` | Capella refused the cluster; nothing was created. Fix the value it names and run the same command |
| `group search exists with 2 × 4/16; use 'capellactl cluster scale …'` | The group exists with another size: change it with `cluster scale --group` or `cluster update --group` |
| `the last group running data cannot be removed` | Every cluster needs a data group; add another data group first if you want to replace it |
| `more than one group runs data` | Name the group to change with `--group SERVICES` |
