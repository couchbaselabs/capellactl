# CAP-060 — Choose the disk type, and see what each type means

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E3 Clusters | P1 | 5 | CAP-017, CAP-041, CAP-051, CAP-052 | Implemented |

## User story
As an **operator deploying a cluster**, I want to choose the disk type for each service group the same way I choose
vCPU and RAM, and see for each type its size range, speed (IOPS) and what it is for, so that I can pick storage that
fits the workload without reading the cloud provider's documentation.

## Context & discovery
- Requested by a customer (2026-10-29): `cluster create` lets them pick the vCPU/RAM combination from a list
  (CAP-051 AC9), but the disk is silently the provider default (`gp3 50 GB 3000 IOPS`, `pd-ssd 50 GB`, `P6`).
  `--disk-type` exists but is not offered, not explained, and not accepted by `cluster update`.
- No new endpoint: the disk is `serviceGroups[].node.disk` in `POST`/`PUT …/clusters` (`DiskAWS`, `DiskAzure`,
  `DiskGCP`). The spec gives only the type enums and minimums and says "see documentation" for sizes and IOPS, so —
  as for node sizes in `config/compute.yaml` — the meaning of each type comes from Capella's documentation (read
  2026-10-29) into a new `config/disks.yaml`:

| Provider | Type | What it is | Size per node | Speed (IOPS) |
|---|---|---|---|---|
| AWS | `gp3` | General-purpose SSD (EBS); default | 50 GB – 16 TB | 3,000 – 16,000, set independently of size |
| AWS | `io2` | Provisioned-IOPS SSD for latency-sensitive, write-heavy workloads; costs more | 50 GB – 16 TB | 3,000 – 64,000 |
| GCP | `pd-ssd` | SSD persistent disk; the only type | 50 GB and up | Follows size: 30 read + 30 write per GB (50 GB → 1,500/1,500); grow the disk to go faster |
| Azure | `P6` … `P60` | Premium SSD v1; size and speed fixed by the type | P6 64 · P10 128 · P15 256 · P20 512 · P30 1,024 · P40 2,048 · P50 4,096 · P60 8,192 GiB | P6 240 · P10 500 · P15 1,100 · P20 2,300 · P30 5,000 · P40/P50 7,500 · P60 16,000 |
| Azure | `Ultra` | Ultra Disk for intensive, transaction-heavy workloads; lowest latency; only in regions that support it | 64, 128, 256, 512 GiB, then 1–15 TiB in 1 TiB steps | Settable, capped by size: 64 → 19,200 · 128 → 38,400 · 256 → 76,800 · 512+ → 80,000 |

- **Recommended IOPS defaults** (Capella docs, "IOPS Defaults"): for `gp3`/`io2`, 3,000 for 50–99 GB, 4,370 for
  100–199, then +1,370 per 100 GB up to 16,000 at 1,000 GB+; Ultra 3,000 at 64 GiB … 16,000 at 1,024 GiB+. Capella
  takes "a value higher than the default but not lower" (100–199 GB may go down to 3,000). `make_disk` sends 3,000
  whatever the size today, so a larger disk can be rejected; this story fixes that.
- Disk changes behave differently per provider (docs, "Storage Auto-Expansion"): on AWS, size or IOPS can change
  once every 6 hours in place, otherwise nodes are replaced and rebalanced; on Azure, a change replaces and
  rebalances nodes. Size cannot be reduced (schema). Auto-expansion is always on for AWS and GCP.

## Design

### Commands
```
capellactl cluster disk-types [--provider aws|gcp|azure]
capellactl cluster create NAME … [--disk-type T] [--disk-size GB] [--disk-iops N]        (existing flags)
capellactl cluster update NAME [--group SERVICES] --disk-type T [--disk-size GB] [--disk-iops N]   (new: --disk-type)
capellactl cluster group add NAME --services S [--disk-type T] …                          (existing flag)
```
Examples:
```
capellactl cluster disk-types --provider aws
capellactl cluster create nova-prod-01 --provider aws --disk-type gp3 --disk-size 200
capellactl cluster update nova-prod-01 --group data --disk-type io2 --disk-iops 20000
```

- **disk-types** lists the provider's types in the list layout (S.NO first):
  `S.NO  PROVIDER  TYPE  SIZE (GB)  IOPS  FOR`, for example
  `1  aws  gp3  50–16000  3000–16000  general purpose (default)`. `-o json` returns `config/disks.yaml` for the
  provider. `cluster options` gains a `disk types` line per provider pointing to `cluster disk-types`.
- **Interactive create and `group add`**: after the node size, a disk picker shows the same table for the chosen
  provider, numbered, default first, then asks only what the type allows: size (with its range; skipped for Azure
  premium) and IOPS (default from the table for that size; skipped for GCP and Azure premium). The flags skip their
  questions.
- **IOPS default follows the size** for `gp3`, `io2` and Ultra (the table above) when `--disk-iops` is not given.
- **`cluster update --disk-type`** changes the type of every group, or of one with `--group`. The plan shows the
  meaning and the cost of the change:
  ```
  ~ cluster nova-prod-01   scale up
    ~ serviceGroups[data].node.disk.type  gp3 → io2  (provisioned IOPS, 3000–64000)
      nodes are replaced and rebalanced
  ```
- **Offline checks** (`validate`, every command before a write) use `config/disks.yaml`: AWS size 50–16,000, IOPS in
  the type's range and not below the default for the size; Azure Ultra size from the spec enum and IOPS ≤ the cap;
  Azure premium refuses size and IOPS (existing rule); GCP refuses IOPS. Messages name the allowed values and point
  to `cluster disk-types`.

### Where the code goes
- `config/disks.yaml` (new, documented source and date like `compute.yaml`), loaded in `config/presets.py`.
- `cli/cluster_ops.py`: `cluster_disk_types`, `_ask_disk()` used by `_ask_groups`, the one-group custom flow and
  `cluster group add`; `make_disk` takes the size-based IOPS default; `cluster update --disk-type`.
- `config/crossref.py`: the range checks.

## Acceptance criteria & tests

### AC1 — List disk types with their meaning
**Given** `cluster disk-types`, **then** every type of every provider is listed with size range, IOPS and use, S.NO
first; `--provider azure` lists only Azure's ten types; `-o json` returns the same data. `cluster options` mentions
`cluster disk-types`.

| Test | Location | Verifies |
|---|---|---|
| `test_disk_types_ac1_list` | `tests/scenario/test_cluster_disk.py` | Text, filter, JSON |
| `test_disk_types_ac1_options_points_to_list` | same | |

### AC2 — Choose interactively
**Given** an interactive `cluster create` on AWS with custom size, **then** after the node size the disk picker
shows gp3 and io2 with their meaning; choosing io2 and 200 GB proposes 5,740 IOPS; the `POST` body has
`{"type": "io2", "storage": 200, "iops": 5740}`. On Azure, choosing `P15` asks nothing more; on GCP, only the size is
asked and the expected IOPS is shown. `cluster group add` asks the same, defaulting to the data group's disk.

| Test | Location | Verifies |
|---|---|---|
| `test_disk_types_ac2_create_picker` | `tests/scenario/test_cluster_disk.py` | Per provider |
| `test_disk_types_ac2_group_add_picker` | same | |

### AC3 — IOPS default follows size
**Given** `--disk-type gp3 --disk-size 500` and no `--disk-iops`, **then** `iops: 9850`; **given** 50 GB, 3,000;
**given** Ultra 256 GiB, 6,000.

| Test | Location | Verifies |
|---|---|---|
| `test_disk_types_ac3_iops_default` | `tests/unit/cli/test_make_disk.py` | Parametrised over the docs table |

### AC4 — Out-of-range values refused offline
**Given** gp3 with 20,000 IOPS, io2 below the size's default, AWS 20,000 GB, Ultra 100 GiB, Ultra IOPS over the cap,
`--disk-iops` on GCP, or size on Azure premium, **then** exit 3 naming the allowed values and `cluster disk-types`,
with zero API calls.

| Test | Location | Verifies |
|---|---|---|
| `test_disk_types_ac4_refused` | `tests/unit/config/test_crossref_disk.py` | Parametrised |

### AC5 — Change the disk type of a running cluster
**Given** `cluster update nova-dev-01 --group data --disk-type io2`, **then** the plan shows the type change with its
meaning and the replacement note, one `PUT` changes only that group's disk, capella.yaml records it, and a re-run is
`no changes` with zero writes. **Given** a type of another provider, **then** exit 3.

| Test | Location | Verifies |
|---|---|---|
| `test_disk_types_ac5_update_type` | `tests/scenario/test_cluster_disk.py` | Plan, PUT body, file |
| `test_disk_types_ac5_rerun_noop_and_wrong_provider` | same | |

### AC6 — Discoverable
**Given** `cluster create --help` and `cluster update --help`, **then** the disk options point to
`cluster disk-types`; `help scaling` has a "Disk types" section. The guide section (`docs/custom-clusters.md` §10)
is made live and tested by CAP-061.

| Test | Location | Verifies |
|---|---|---|
| `test_disk_types_ac6_help` | `tests/scenario/test_cluster_disk.py` | |

## Out of scope
- Prices per disk type: Capella's API has no price list; the table says which types cost more.
- Checking Ultra availability per region: the API does not list it; Capella rejects it with its own message.

## Implementation notes (as built)
- `capellactl/config/disks.yaml` (Capella documentation, read 2026-10-29; packaged in the wheel and the executable)
  and its helpers in `config/presets.py`: `load_disk_types`, `default_iops`, `iops_range`. Google Cloud has no
  documented maximum size, so only the minimum (50 GB) is checked.
- `cluster disk-types [--provider P]` (list layout, `-o json`); `cluster options` names each provider's types and
  points to it (`diskTypes` in JSON).
- The disk picker (`_ask_disk`) is asked after the node size in the interactive custom create (one group and each
  group of several) and in `cluster group add` (default: the data group's disk). Azure premium types ask nothing
  more; Google Cloud asks the size and shows the IOPS it gives.
- `make_disk` now gives gp3, io2 and Ultra disks Capella's recommended IOPS for their size when none is given (it
  sent 3000 for every size), and an Ultra disk the smallest Ultra size (64 GB, not 50). CAP-051 AC5's expected
  bodies were updated (100 GB → 4370 IOPS, 200 GB → 5740).
- `cluster update --disk-type` changes **the group chosen with `--group` (default: the data group)**, like the other
  update options, not every group as the design said. The size is kept when the new type allows it; IOPS become the
  recommendation unless `--disk-iops` is given. The lines under the plan say what the type is for and that Capella
  may replace and rebalance the nodes.
- **AC4 deviation:** sizes and IOPS outside a type's range are errors (exit 3), but IOPS **below the recommendation**
  are a warning, not an error: clusters brought in by `sync` may have older, lower values that Capella still runs.
  `--disk-iops` on Google Cloud is refused by the commands rather than by validation, for the same reason.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_disk_types_ac1_list`, `test_disk_types_ac1_options_points_to_list` (tests/scenario/test_cluster_disk.py) |
| AC2 | `test_disk_types_ac2_create_picker`, `test_disk_types_ac2_group_add_picker` |
| AC3 | `test_disk_types_ac3_iops_default`, `test_disk_types_ac3_defaults_per_provider` (tests/unit/cli/test_make_disk.py) |
| AC4 | `test_disk_types_ac4_refused`, `test_disk_types_ac4_accepted`, `test_disk_types_ac4_below_recommended_warns` (tests/unit/config/test_crossref_disk.py) |
| AC5 | `test_disk_types_ac5_update_type`, `test_disk_types_ac5_rerun_noop_and_wrong_provider` |
| AC6 | `test_disk_types_ac6_help` |
