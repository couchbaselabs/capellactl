# CAP-051 — Create multi-dimensional (MDS) clusters from the CLI

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E3 Clusters | P0 | 13 | CAP-011, CAP-015, CAP-038, CAP-049 | Implemented |

## User story
As an **operator**, I want to create a cluster with several service groups, each with its own services, node count, compute and disk (multi-dimensional scaling), using `capellactl cluster create` only, so that I can deploy production layouts (for example dedicated data, index/query and search nodes) without editing capella.yaml.

## Context & discovery
- Product decision (CAP-038, 2026-10-05): **capella.yaml is owned by the tool; users never edit it.** Confirmed again on 2026-10-23: a multi-dimensional layout must not need a YAML edit either.
- Today `cluster create` writes exactly **one** service group (`--nodes/--cpu/--ram/--services`, [cluster_ops.py](../../capellactl/cli/cluster_ops.py) `cluster_create`). `cluster scale --group` and `cluster update --group` only change groups that already exist (`no service group '…'`). The only way to get a second group is to edit capella.yaml and run `apply` (CAP-015 "Declarative"). This story closes that gap at create time; CAP-052 closes it for existing clusters.
- The API already supports it: `POST …/projects/{projectId}/clusters` takes `serviceGroups[]`, each with `node.compute{cpu, ram}`, `node.disk`, `numOfNodes`, `services` (CAP-011 create body). **No new endpoint.**
- Everything below the CLI already supports several groups: the schema (`serviceGroups`, `minItems: 1`), the offline rules in `config/crossref.py` (one group runs `data`; first group 3–27 nodes, others 2–24; ≤ 27 in total; disk rules per provider), the plan, the reconciler, `import`/`sync` and `cluster clone`. The story is therefore CLI input, prompts and messages; the engine is reused unchanged.
- Groups are identified by their sorted services set, the *group key* (CAP-015). `--group SERVICES` already means "this group" in `cluster scale` and `cluster update`; the create form below starts with the same group key so the flag means the same thing everywhere.

## Design

### Command line
```
capellactl cluster create NAME --group SPEC [--group SPEC …] [other create options]

SPEC      SERVICES:NODESxCPU/RAM[:DISK]
SERVICES  comma-separated services (data, index, query, search, analytics, eventing)
NODES     nodes in the group
CPU/RAM   vCPUs and GB of RAM per node
DISK      comma-separated key=value: type, size (GB), iops, auto-expansion (azure: true|false)
```

Examples:
```
capellactl cluster create nova-prod-01 --provider aws --region us-east-1 \
  --group data:3x8/32 \
  --group index,query:2x8/32 \
  --group search:2x4/16

capellactl cluster create nova-prod-02 --provider aws \
  --group data,index,query:3x8/32:size=100 \
  --group analytics:2x16/64:size=200,iops=5000
```

- `NODESxCPU/RAM` reads like the plan line (`3 × 8 vCPU/32 GB`), so what is typed is what is shown.
- `DISK` keys not given take the provider default (`gp3` 50 GB 3000 IOPS on aws, `pd-ssd` 50 GB on gcp, `P6` on azure), the same as single-group create. `--disk-type/--disk-size/--disk-iops` on the command line set the default for every group that does not name its own.
- `--group` replaces the single-group flags: combining it with `--nodes`, `--cpu`, `--ram`, `--services` or `--size` exits 3 (`--group sets nodes, size and services per group; remove --nodes/--cpu/--ram/--services/--size`).
- One `--group` is allowed (a custom single group in one flag); two or more makes an MDS cluster.
- Group order: groups are written in the order given, except that when the first group does not run `data`, the first group that does is moved to the front, so the "first group 3–27 nodes" rule applies to a data group (open question 1).

### Interactive
With no size options in an interactive terminal, `Size` gains a `custom` answer that is followed by:
```
Service layout (one group, multiple groups) [one group]: multiple groups
Service group 1
  Services [data,index,query,search,analytics,eventing]: data
  Nodes (3–27) [3]: 3
  Node size (vCPU / RAM GB):
    1) 4 / 16   2) 8 / 32   3) 16 / 64   …   (from config/compute.yaml for the provider)
  Choose [1]: 2
  Disk GB per node [50]:
Add another service group? [y/N]: y
Service group 2  (nodes so far: 3 of 27)
  Services [index,query,search,analytics,eventing]: index,query
  Nodes (2–24) [2]:
  …
Add another service group? [y/N]: n
```
- The `Services` default is the services no group runs yet (every service for the first group).
- Each answer is checked as it is given (unknown service, a services set already used, node limits, the running total ≤ 27), and only that answer is asked again.
- The node size is chosen from the known sizes for the provider (see "Getting the spec right"), not typed, so an interactive create cannot ask for a size Capella does not offer. `other` at the end of the list still allows typing vCPUs and RAM.
- `one group` keeps today's questions (nodes, vCPUs, RAM) unchanged.
- The summary line lists every group: `New cluster nova-prod-01 in project nova: aws us-east-1, 3 groups · 7 nodes (data 3 × 8/32 · index,query 2 × 8/32 · search 2 × 4/16), network 10.0.10.0/24, support developer pro`.

### Getting the spec right
The Management API has no dry-run or validate-only call and no endpoint that lists the compute sizes offered per provider or region (checked against the spec snapshot; CAP-041). A wrong spec is therefore stopped in layers, as early as possible, and never leaves a half-built cluster or a capella.yaml that disagrees with Capella:

| Layer | What it catches | Where | Result |
|---|---|---|---|
| 1. Parse | Typos and shape: `data:3x8`, `dat:3x8/32`, `size=abc` | `parse_group_spec` (AC2) | Exit 3 naming the part, with a suggestion (`did you mean data?`, `expected NODESxCPU/RAM, e.g. 3x8/32`). Nothing written or sent. |
| 2. Rules | Rules from the spec: a data group, node limits, total ≤ 27, disk type per provider, unique services sets | existing `validate` rules (AC3–AC5) | Exit 3 before any request. |
| 3. Known sizes | A vCPU/RAM pair that Capella does not offer (`8x30`) | `config/compute.yaml` (AC9) | Interactive: not offered. Flags: a `!` warning in the plan, before the confirmation. |
| 4. Review | Anything the operator did not mean | the plan (AC1) | Every group expanded with its defaults (`2 × 8 vCPU/32 GB gp3 50 GB 3000 IOPS`) and confirmed once. |
| 5. Capella | What only Capella knows: a size not offered in this region, plan limits | `POST …/clusters` (AC10) | `422`: nothing is created, Capella's message and hint are shown and capella.yaml is restored (CAP-038 AC8); fix and re-run the same command. Accepted but `deploymentFailed` later: CAP-011 AC4 (never auto-deleted; delete and re-run). |

**Known sizes** (`config/compute.yaml`, next to `presets.yaml`): the vCPU/RAM pairs per provider, taken from the Capella documentation (never from memory, CONTRIBUTING) with the source and date in the file's header, and changed without code changes. A size outside the table **warns but does not refuse**: Capella adds sizes, and layer 5 still protects the customer when the table is behind. `cluster options` lists the table per provider.

### Copying a layout that already exists
`cluster clone SOURCE NEW_NAME --region REGION --no-data-model` (CAP-049) already copies every service group of a cluster, including clusters made in the Capella UI, because it reads the source live from Capella. It is the safest way to repeat a working layout (same region is allowed after a confirmation; `--to-project` for another project), so this story adds no `--groups-from` option. `cluster create --help` and `help scaling` point to it.

### Flow (unchanged from CAP-038)
Build the cluster entry → validate the candidate file → show the plan → ask once → write capella.yaml → `POST` → wait until healthy. `--no-apply` only records it. A rejected create restores the file (as today).

### Plan output
```
  + cluster nova-prod-01  aws us-east-1 · multi-AZ · 3 service groups · 7 nodes · developer pro
      + serviceGroups[data]         3 × 8 vCPU/32 GB gp3 50 GB
      + serviceGroups[index,query]  2 × 8 vCPU/32 GB gp3 50 GB
      + serviceGroups[search]       2 × 4 vCPU/16 GB gp3 50 GB
```
A single-group create keeps today's one-line summary.

### Where the code goes
- `cli/cluster_ops.py`: `parse_group_spec(text, provider) -> dict` (one service-group dict, or `CliExit(CONFIG_INVALID)` naming the bad part with a suggestion), `--group` option (`multiple=True`), the interactive loop, and the summary line.
- `config/compute.yaml` + a loader in `config/presets.py` (same pattern as `presets.yaml`); the unknown-size warning is a plan note, like the scale-in `checks:` line.
- Disk defaults per group come from the existing `DISK_DEFAULT` and `fixed_size_disk`.
- No change to the schema, reconciler, normalizer or API client.

## Acceptance criteria & tests

### AC1 — Create an MDS cluster with flags
**Given** `capellactl --auto-approve cluster create nova-prod-01 --provider aws --group data:3x8/32 --group index,query:2x8/32 --group search:2x4/16`, **then** the plan line says `3 service groups · 7 nodes` with one `+ serviceGroups[…]` line per group, one `POST …/clusters` is sent whose `serviceGroups` are the three groups (sorted services, default aws disks), the tool waits until healthy, and capella.yaml records the three groups.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_mds_ac1_create_body_matches_fixture` | `tests/scenario/test_cluster_create_mds.py` | POST body |
| `test_cluster_mds_ac1_plan_lines_per_group` | same | Plan text |

### AC2 — Group spec parsing and errors
**Given** each spec below, **then** it parses to the expected group or exits 3 with a message naming the part that is wrong, before any request: `data:3x8/32` (ok); `data,index:3x8/32:size=100,iops=5000` (ok); `data:3x8` (`expected NODESxCPU/RAM, e.g. 3x8/32`); `data:three x8/32`; `data:3x8/32:size=abc`; `data:3x8/32:speed=1` (`unknown disk option 'speed'; use type, size, iops, auto-expansion`); `cache:3x8/32` (`unknown service 'cache'`); `dat:3x8/32` (`unknown service 'dat'; did you mean data?`); `data:3x8/32x` and `data:3*8/32` (`expected NODESxCPU/RAM, e.g. 3x8/32`); `:3x8/32` (no services).

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_mds_ac2_parse_group_spec` | `tests/unit/cli/test_group_spec.py` | Parametrised |
| `test_cluster_mds_ac2_parse_errors` | same | Parametrised |

### AC3 — Conflicting and duplicate options are refused
**Given** `--group` together with any of `--nodes`, `--cpu`, `--ram`, `--services`, `--size`, **then** exit 3 naming the conflicting flags. **Given** two `--group` values with the same services set in any order (`index,query` and `query,index`), **then** exit 3 `two groups run index,query; each group needs a different set of services`. Nothing is written to capella.yaml.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_mds_ac3_conflicting_flags` | `tests/scenario/test_cluster_create_mds.py` | |
| `test_cluster_mds_ac3_duplicate_group_key` | same | |

### AC4 — Limits checked before any request
**Given** groups that break a rule, **then** exit 3 with the existing `validate` message and zero requests: no group runs `data`; the data group has 2 nodes; an additional group has 25 nodes; 28 nodes in total; `--group` twice with `--size dev` or on a single-node cluster (`singleNode clusters have exactly one service group`). **Given** `--group search:2x4/16 --group data:3x8/32`, **then** the data group is sent first and the create succeeds.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_mds_ac4_limits` | `tests/scenario/test_cluster_create_mds.py` | Parametrised |
| `test_cluster_mds_ac4_data_group_first` | same | |
| `test_cluster_mds_ac4_single_node_one_group` | same | |

### AC5 — Disk per group
**Given** `--disk-size 100 --group data:3x8/32 --group index,query:2x8/32:size=200`, **then** the data group gets 100 GB and the index/query group 200 GB, both with the provider's default type and IOPS. **Given** gcp, **then** no `iops` is sent; **given** azure with `auto-expansion=true`, **then** `autoExpansion: true` is sent for that group; **given** aws with `auto-expansion=true`, **then** exit 3 `autoExpansion is for azure disks only`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_mds_ac5_disk_per_group` | `tests/scenario/test_cluster_create_mds.py` | Parametrised by provider |
| `test_cluster_mds_ac5_auto_expansion_azure_only` | same | |
| `test_cluster_mds_ac5_disk_defaults_per_provider` | `tests/unit/cli/test_group_spec.py` | |

### AC6 — Interactive multi-group create
**Given** an interactive terminal and the answers `custom`, `multiple groups`, then two groups, **then** the cluster entry has both groups and the summary lists them. **Given** an answer that breaks a rule (unknown service, a repeated services set, 25 nodes, a total over 27), **then** only that question is asked again with the reason. **Given** `one group`, **then** the questions are exactly today's.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_mds_ac6_interactive_two_groups` | `tests/scenario/test_cluster_create_mds.py` | |
| `test_cluster_mds_ac6_interactive_reasks_bad_answer` | same | |
| `test_cluster_mds_ac6_one_group_keeps_questions` | same | |
| `test_cluster_mds_ac6_default_is_unused_services` | same | |
| `test_cluster_mds_ac6_choice_accepts_start_of_answer` | `tests/unit/cli/test_group_spec.py` | `multiple`, `m`, `developer` |
| `test_cluster_mds_ac6_choice_refuses_ambiguous_or_unknown` | same | |

### AC7 — File and Capella agree; idempotent re-run
**Given** AC1 completed, **then** `plan` reports no changes and `apply` makes zero writes; `-o json` of the create contains every group; `cluster create nova-prod-01 …` again exits 4 (already exists) with zero writes. **Given** `--no-apply`, **then** only capella.yaml changes and a later `apply` sends the same `POST` as AC1.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_mds_ac7_rerun_zero_writes` | `tests/scenario/test_cluster_create_mds.py` | |
| `test_cluster_mds_ac7_no_apply_then_apply` | same | |

### AC8 — Discoverable
**Given** `cluster create --help`, **then** it shows the `SPEC` format and an MDS example. **Given** `cluster options`, **then** it lists the services and the service-group limits (first group 3–27, others 2–24, ≤ 27 nodes, one group runs data). **Given** `help scaling`, **then** it explains creating an MDS cluster with `--group`. A step-by-step guide, `docs/custom-clusters.md` (linked from the README, getting started and the runbook), has every command run in order against the fake Capella.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_mds_ac8_help_and_options` | `tests/scenario/test_cluster_create_mds.py` | |
| `test_cluster_mds_ac8_guide_steps` | `tests/scenario/test_custom_clusters_guide.py` | |

### AC9 — Known sizes guide the choice
**Given** `config/compute.yaml` lists the sizes for aws, **then** the interactive node-size question offers exactly those sizes (plus `other`). **Given** `--group data:3x8/30` on aws, **then** the plan shows `! serviceGroups[data]: 8 vCPU/30 GB is not a known aws size; Capella may reject it (see 'capellactl cluster options')` before the confirmation, and the create still proceeds when confirmed. **Given** a listed size, **then** no warning. **Given** `cluster options`, **then** the sizes are listed per provider. Changing the file changes the choices without a code change.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_mds_ac9_interactive_offers_known_sizes` | `tests/scenario/test_cluster_create_mds.py` | |
| `test_cluster_mds_ac9_unknown_size_warns` | same | |
| `test_compute_sizes_ac9_loaded_from_file` | `tests/unit/config/test_compute_sizes.py` | |

### AC10 — A spec Capella rejects leaves nothing behind
**Given** an MDS create that Capella answers with `422` (for example a size not offered in the region), **then** Capella's `message` and `hint` are printed, exit 1, no cluster exists, capella.yaml is byte-for-byte what it was before the command, and the same command with the corrected `--group` succeeds. **Given** Capella accepts the create and the cluster ends in `deploymentFailed`, **then** exit 1 with the CAP-011 AC4 message (delete it, then re-run) and the cluster is not deleted automatically.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_mds_ac10_422_restores_file` | `tests/scenario/test_cluster_create_mds.py` | |
| `test_cluster_mds_ac10_deployment_failed_not_deleted` | same | |

## Out of scope
- A `--groups-from CLUSTER` option: `cluster clone --no-data-model` (CAP-049) already copies a cluster's layout.
- Adding, removing or listing groups on an existing cluster (CAP-052).
- Server version, zone, CMEK, private DNS and the explicit single-node flag (CAP-053).
- Multi-group size presets in `config/presets.yaml` (open question 2).
- Changing a group's services set in place (remove and add, CAP-052).

## Open questions
1. Does Capella apply the 3-node minimum to the **first** group in the request or to the group that runs **data**? The offline rule checks the first group; putting a data group first satisfies both readings. Confirm in the sandbox and simplify the rule if it is the data group.
2. Should presets be able to describe several groups (for example `mds-small`: data 3 × 8/32 + index,query 2 × 8/32)? Proposed: not in this story; revisit after customer feedback.
3. ~~Which Capella documentation page is the source for `config/compute.yaml`?~~ Answered 2026-10-23: the per-provider reference pages (`docs.couchbase.com/cloud/reference/{aws,gcp,azure}.html`). They list sizes per provider, not per region, so region-level gaps are left to layer 5.
4. With `availability: multi`, must each group's node count be a multiple of the zone count? (Carried over from CAP-015.) If so, add the rule to `validate` and to the interactive checks.
5. The AWS reference page says disk auto-expansion is supported on AWS, but the Management API spec defines `autoExpansion` only on the Azure disk (`DiskAzure`). capellactl follows the spec (`autoExpansion is for azure disks only`); confirm with Capella and relax the rule if the API accepts it for AWS.

## Implementation notes (as built)
- `--group SERVICES:NODESxCPU/RAM[:DISK]` (`cli/cluster_ops.py`: `parse_group_spec`, `parse_services`, `make_disk`, `data_first`). Unknown services get a `difflib` suggestion; every message starts with `--group <spec>:` so the bad flag is obvious when several are given.
- The plan keeps the one-line summary for a single group. For several groups the summary says `N service groups · M nodes` and each group is a `+ serviceGroups[…]` remark under it (`resources/cluster.py::create_group_lines`); the JSON plan carries them as `notes`. The disk is shown as type and size (as in scale-out lines), not IOPS, so plan lines stay the same everywhere.
- `config/compute.yaml` was filled from the three Capella reference pages on 2026-10-23 (2/8 is listed only for single-node clusters). `config/presets.py::known_size` checks it; the warning is an `after_plan` line, so it appears after the plan and before the `[y/N]` question, and it applies to single-group creates too. `cluster options` (text and JSON) lists services, group limits and the sizes.
- New offline rules in `config/crossref.py`, also used by `apply`: two groups with the same services set; `autoExpansion` on a non-Azure disk; services outside `data, index, query, search` on a single-node cluster.
- A data group is moved to the front only when the first group does not run data; otherwise the order given is kept.
- `--disk-type` on AWS now also defaults `iops` to 3000 (the lowest value Capella accepts), so `--disk-type io2` no longer fails validation for a missing `iops`.
- Choice questions in `cluster create` take any unambiguous start of an answer, case-insensitive (`multiple` or `m` for `multiple groups`, `developer` for `developer pro`; `cli/cluster_ops.py::PrefixChoice`), added 2026-10-23 after `multiple` was refused.
- The interactive flow keeps its retry loop: an answer re-asked by the CIDR/region checks keeps the groups already answered.
- AC8's guide is `docs/custom-clusters.md` (a separate guide rather than a getting-started step, by request on 2026-10-23); `tests/scenario/test_custom_clusters_guide.py` runs its commands in order.
- The fake Capella gained `fail_deploy_next` for AC10 (accepted create that ends in `deploymentFailed`).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_cluster_mds_ac1_create_body_matches_fixture`, `test_cluster_mds_ac1_plan_lines_per_group` (tests/scenario/test_cluster_create_mds.py) |
| AC2 | `test_cluster_mds_ac2_parse_group_spec`, `test_cluster_mds_ac2_parse_errors` (tests/unit/cli/test_group_spec.py) |
| AC3 | `test_cluster_mds_ac3_conflicting_flags`, `test_cluster_mds_ac3_duplicate_group_key` (tests/scenario/test_cluster_create_mds.py) |
| AC4 | `test_cluster_mds_ac4_limits`, `test_cluster_mds_ac4_single_node_one_group`, `test_cluster_mds_ac4_data_group_first` (tests/scenario/test_cluster_create_mds.py) |
| AC5 | `test_cluster_mds_ac5_disk_per_group`, `test_cluster_mds_ac5_auto_expansion_azure_only` (tests/scenario/test_cluster_create_mds.py)<br>`test_cluster_mds_ac5_disk_defaults_per_provider` (tests/unit/cli/test_group_spec.py) |
| AC6 | `test_cluster_mds_ac6_interactive_two_groups`, `test_cluster_mds_ac6_interactive_reasks_bad_answer`, `test_cluster_mds_ac6_one_group_keeps_questions`, `test_cluster_mds_ac6_default_is_unused_services` (tests/scenario/test_cluster_create_mds.py)<br>`test_cluster_mds_ac6_choice_accepts_start_of_answer`, `test_cluster_mds_ac6_choice_refuses_ambiguous_or_unknown` (tests/unit/cli/test_group_spec.py) |
| AC7 | `test_cluster_mds_ac7_rerun_zero_writes`, `test_cluster_mds_ac7_no_apply_then_apply` (tests/scenario/test_cluster_create_mds.py) |
| AC8 | `test_cluster_mds_ac8_help_and_options` (tests/scenario/test_cluster_create_mds.py)<br>`test_cluster_mds_ac8_guide_steps` (tests/scenario/test_custom_clusters_guide.py) |
| AC9 | `test_cluster_mds_ac9_interactive_offers_known_sizes`, `test_cluster_mds_ac9_unknown_size_warns` (tests/scenario/test_cluster_create_mds.py)<br>`test_compute_sizes_ac9_loaded_from_file` (tests/unit/config/test_compute_sizes.py) |
| AC10 | `test_cluster_mds_ac10_422_restores_file`, `test_cluster_mds_ac10_deployment_failed_not_deleted` (tests/scenario/test_cluster_create_mds.py) |
