# CAP-053 — Advanced cluster create options: server version, single node, zone, CMEK, private DNS, disk auto-expansion

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E3 Clusters | P1 | 5 | CAP-011, CAP-038, CAP-051 | Implemented |

## User story
As an **operator**, I want every field the Capella create-cluster API accepts to be available as a `cluster create` option, so that I never have to edit capella.yaml to get the cluster I need.

## Context & discovery
Create body fields (CAP-011, from the spec) and how the CLI offers them today:

| API field | Schema (`config/schema.json`) | `cluster create` today | This story |
|---|---|---|---|
| `name`, `description` | yes | argument, `--description` | — |
| `cloudProvider.type/region/cidr` | yes | `--provider`, `--region`, `--cidr` | — |
| `serviceGroups[]` | yes | one group; several with CAP-051 | — |
| `availability.type` | yes | `--availability` | — |
| `support.plan/timezone` | yes | `--support-plan`, `--support-timezone` | — |
| `configurationType` | yes | only through `--size dev` (fixed 4 vCPU/16 GB) | `--single-node` |
| `couchbaseServer.version` | yes | — | `--server-version` |
| `zones` | yes (≤ 1, single-AZ) | — | `--zone` |
| `cmekId` | yes | — | `--cmek-id` |
| `enablePrivateDNSResolution` | yes | — | `--private-dns` |
| `serviceGroups[].node.disk.autoExpansion` | yes (azure) | — | `--disk-auto-expansion` (and CAP-051 `auto-expansion=`) |

- All of these are already accepted by the schema, the offline rules (CAP-011 AC5: `zones` single-AZ only, one entry) and the reconciler (`resources/cluster.py` `CREATE_FIELDS`). `import` already records the version, `cmekId`, `enablePrivateDNSResolution` and `autoExpansion`; `zones` is not returned by `GET …/clusters/{id}`, so it is kept from the file and never compared. The gap is the command line only. **No new endpoint.**
- All are immutable after create (`x-mutability: immutable`) except `autoExpansion` (updatable). Changing an immutable one later is BLOCKED by the existing CAP-012 rule.
- There is no catalog endpoint for server versions or zones (CAP-041). Values are passed through; Capella's `422` message and hint are shown (CAP-011 AC6).

## Design

### New `cluster create` options
| Option | Sends | Rules checked before any request |
|---|---|---|
| `--server-version VERSION` | `couchbaseServer.version` | shape `N.N` or `N.N.N` |
| `--single-node` | `configurationType: singleNode`, `availability.type: single`, one group with 1 node | not with `--nodes` ≠ 1, `--group` twice, `--availability multi`; services only from `data, index, query, search`; takes `--cpu/--ram/--disk-*` (default 4/16), so a custom-sized single node no longer needs `--size dev` |
| `--zone ZONE` | `zones: [ZONE]` | needs `--availability single` (or `--single-node`) |
| `--cmek-id ID` | `cmekId` | non-empty; key must already exist (managing CMEK keys is out of scope) |
| `--private-dns` | `enablePrivateDNSResolution: true` | — (Capella decides where it is supported; open question) |
| `--disk-auto-expansion` | `autoExpansion: true` on every group without its own value | azure only |

- These are **advanced** options: the interactive flow does not ask for them, so the guided create stays short. `cluster create --help` lists them under an `Advanced options` heading.
- `cluster update --disk-auto-expansion/--no-disk-auto-expansion [--group SERVICES]` changes the updatable field (CAP-017 vertical path, Azure only).
- The plan line shows what was set: `+ cluster nova-prod-01  azure eastus · single-AZ (zone 1) · Couchbase 8.0 · CMEK · private DNS · …`.
- `cluster options` adds the server versions already used by the organization's clusters (as suggestions, like regions in CAP-041).

### Where the code goes
- `cli/cluster_ops.py`: the new options on `cluster_create` (and `--disk-auto-expansion` on `cluster_update`), written into the entry before `_validate_candidate`.
- `config/crossref.py`: rules for `--single-node` services and auto-expansion on non-azure disks, if not already there.

## Acceptance criteria & tests

### AC1 — Each option reaches the create body
**Given** `cluster create` with each new option in turn, **then** the `POST` body carries exactly the field in the table above and nothing else changes; capella.yaml records it; a later `plan` reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_adv_ac1_option_in_body` | `tests/scenario/test_cluster_create_advanced.py` | Parametrised by option |
| `test_cluster_adv_ac1_auto_expansion_in_body` | same | |

### AC2 — Custom-sized single node
**Given** `cluster create nova-dev-03 --single-node --cpu 8 --ram 32`, **then** the body has `configurationType: singleNode`, `availability.type: single` and one group with 1 × 8/32 running `data, index, query`. **Given** `--single-node` with `--nodes 3`, `--availability multi`, two `--group` values or `--services analytics`, **then** exit 3 naming the rule and zero requests.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_adv_ac2_single_node_custom` | `tests/scenario/test_cluster_create_advanced.py` | |
| `test_cluster_adv_ac2_single_node_refused` | same | Parametrised |

### AC3 — Rules checked offline
**Given** `--zone` with multi-AZ availability, `--disk-auto-expansion` on aws or gcp, `--server-version latest`, or an empty `--cmek-id`, **then** exit 3 with a specific message and zero requests.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_adv_ac3_rules` | `tests/scenario/test_cluster_create_advanced.py` | Parametrised |

### AC4 — Capella's answer is shown
**Given** Capella answers `422` to an unknown version, zone or CMEK key, **then** its `message` and `hint` are printed, exit 1, and capella.yaml is restored (CAP-011 AC6).

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_adv_ac4_422_restores_file` | `tests/scenario/test_cluster_create_advanced.py` | |

### AC5 — Immutable after create, auto-expansion updatable
**Given** a cluster created with `--server-version 7.6`, **then** a different version in the file is BLOCKED by the CAP-012 rule (server upgrades are out of scope). **Given** an azure cluster, **then** `cluster update NAME --disk-auto-expansion` sends one `PUT` with `autoExpansion: true` on the data group (or on `--group`); on aws it exits 3.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_adv_ac5_version_immutable` | `tests/scenario/test_cluster_create_advanced.py` | |
| `test_cluster_adv_ac5_update_auto_expansion` | same | |

### AC6 — Help and options
**Given** `cluster create --help`, **then** the new options appear under `Advanced options` with an example. **Given** `cluster options`, **then** server versions in use are listed. `capellactl help config clusters.zones` (and each field above) names its `cluster create` option.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_adv_ac6_help_and_options` | `tests/scenario/test_cluster_create_advanced.py` | |

### AC7 — Idempotent re-run and import round trip
**Given** AC1 completed, **then** `apply` makes zero writes. **Given** a cluster with these fields created outside capellactl, **then** `import` records every field `GET` returns (all but `zones`) and a plan reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_adv_ac7_rerun_zero_writes` | `tests/scenario/test_cluster_create_advanced.py` | |
| `test_cluster_adv_ac7_import_round_trip` | same | |

## Out of scope
- Creating or rotating CMEK keys (`cmek …` commands, not in 1.0.0).
- Upgrading the server version of an existing cluster.
- Listing zones or versions Capella offers (no catalog endpoint, CAP-041).

## Open questions
- Which providers and plans support `enablePrivateDNSResolution`? The spec does not say; rely on Capella's `422` until it is documented.
- Are zone names provider-specific in shape (for example `use1-az1` on aws)? If so, add a shape check like the region one in CAP-011 AC6.

## Implementation notes (as built)
- The options are on `cluster create` in `cli/cluster_ops.py`; `--help` lists them under **Advanced options (not asked; set only on the command line)** through a small `click.Command` subclass. `--disk-auto-expansion/--no-disk-auto-expansion` is a pair so "not given" stays distinct from "off".
- Combinations that cannot work are refused before anything is read (`_check_create_options`): `--single-node` with `--size`, `--nodes` ≠ 1, `--availability multi` or two `--group`; a `--server-version` that is not `N.N` or `N.N.N`; an empty `--cmek-id`. `--zone` without single-AZ, `autoExpansion` outside Azure and single-node services come from `validate` (`config/crossref.py`), so `apply` checks them too.
- `--single-node` takes `--cpu/--ram` (default 4/16) and a single `--group` (with 1 node).
- `cluster update --disk-auto-expansion` (Azure only, exit 3 elsewhere) changes the updatable field through the normal vertical-scale path.
- `help config` for `zones`, `cmekId`, `enablePrivateDNSResolution`, `couchbaseServer.version`, `configurationType` and `autoExpansion` names the option that sets it (schema descriptions; `docs/reference.md` regenerated).
- `cluster options` lists the server versions the organization's clusters use.
- The AWS reference page says AWS disks support auto-expansion, but the API spec has `autoExpansion` only on the Azure disk; capellactl follows the spec (see CAP-051 open question 5).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_cluster_adv_ac1_option_in_body`, `test_cluster_adv_ac1_auto_expansion_in_body` (tests/scenario/test_cluster_create_advanced.py) |
| AC2 | `test_cluster_adv_ac2_single_node_custom`, `test_cluster_adv_ac2_single_node_refused` (tests/scenario/test_cluster_create_advanced.py) |
| AC3 | `test_cluster_adv_ac3_rules` (tests/scenario/test_cluster_create_advanced.py) |
| AC4 | `test_cluster_adv_ac4_422_restores_file` (tests/scenario/test_cluster_create_advanced.py) |
| AC5 | `test_cluster_adv_ac5_version_immutable`, `test_cluster_adv_ac5_update_auto_expansion` (tests/scenario/test_cluster_create_advanced.py) |
| AC6 | `test_cluster_adv_ac6_help_and_options` (tests/scenario/test_cluster_create_advanced.py) |
| AC7 | `test_cluster_adv_ac7_rerun_zero_writes`, `test_cluster_adv_ac7_import_round_trip` (tests/scenario/test_cluster_create_advanced.py) |
