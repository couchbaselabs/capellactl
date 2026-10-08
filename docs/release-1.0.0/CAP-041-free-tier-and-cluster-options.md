# CAP-041 — Free-tier clusters and available cluster options

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E3 Clusters | P0 | 5 | CAP-011, CAP-038, CAP-040 | Implemented |

## User story
As an **operator trying Capella**, I want to deploy a free single-node cluster with capellactl, and to see only the cluster options that are actually available to me, so that I can test without guessing what Capella will accept.

## Context & discovery
From the Management API spec (`POST/GET/PUT/DELETE …/clusters/freeTier[/{clusterId}]`):
- A free-tier cluster is **1 node** running data, index, query and search. **At most one per organization.**
- Only `name`, `description`, `cloudProvider.type`, `cloudProvider.region` and `cloudProvider.cidr` are configurable; after creation only name and description can change (`PUT`, `412` on stale ETag).
- Regions are fixed: AWS `us-east-2`, `eu-west-1`, `ap-southeast-1`; GCP `us-central1`, `europe-west1`, `asia-east1`; Azure `eastus`, `swedencentral`, `koreacentral`.
- Not available on free tier: backup/restore, private endpoints, network peering, audit logs, alert integration, CMEK, on/off schedule. `GET` returns `support.plan: free`.
- Create returns `202`; a second free-tier cluster returns `422`.

**Option discovery:** the Management API has **no endpoint that lists** the providers, regions, compute sizes or server versions an organization may use. capellactl therefore shows:
- the free tier only when no free-tier cluster exists in any project of the organization, with its documented regions;
- for provisioned clusters, the providers, size presets and support plans from the spec, plus the regions the organization's clusters already use as suggestions; other regions are accepted and validated by Capella.

## Implementation details
- capella.yaml: a free-tier cluster is `tier: free` with `name`, `description`, `cloudProvider` (and its `id`, recorded after creation). Provisioned clusters are unchanged (`tier` defaults to `provisioned`).
- Commands:
  - `capellactl cluster options [--project NAME]`: what can be deployed now.
  - `capellactl cluster create NAME --free-tier [--provider --region --cidr]`: interactive mode first asks `Cluster type` and offers `free` only when available.
- Reconciler: free-tier clusters are created, read, renamed and described through the `freeTier` endpoints and waited on until healthy; scaling, sizing and support-plan changes are refused with a clear message.

## Acceptance criteria & tests

### AC1 — Options show what is available
**Given** no free-tier cluster in the organization, **then** `cluster options` shows the free tier as available with its 9 regions grouped by provider, and the provisioned options (providers, sizes, support plans, regions in use). **Given** a free-tier cluster already exists (in any project), **then** the free tier is shown as not available, naming that cluster.

| Test | Location | Verifies |
|---|---|---|
| `test_options_ac1_free_tier_available` | `tests/scenario/test_free_tier.py` | |
| `test_options_ac1_free_tier_used` | same | |

### AC2 — Deploy a free-tier cluster
**Given** `capellactl --auto-approve cluster create try-01 --free-tier --provider aws --region us-east-2`, **then** one `POST …/clusters/freeTier` is sent with `{name, cloudProvider}`, the tool waits until healthy, and capella.yaml records the cluster with `tier: free` and its `id`. A plan afterwards reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_free_tier_ac2_create_and_record` | `tests/scenario/test_free_tier.py` | |

### AC3 — Interactive create offers only available choices
**Given** the free tier is available, **then** the first question is `Cluster type (free, provisioned)` and choosing `free` asks only provider, a region from the free-tier list, and the network. **Given** the free tier is already used, **then** `free` is not offered and `--free-tier` exits 4 naming the existing free-tier cluster.

| Test | Location | Verifies |
|---|---|---|
| `test_free_tier_ac3_interactive_choices` | `tests/scenario/test_free_tier.py` | |
| `test_free_tier_ac3_not_offered_when_used` | same | |

### AC4 — Free-tier rules are validated
**Given** a free-tier entry with a region outside the list, with `serviceGroups`/`support`/`availability`, or two free-tier clusters in the file, **then** `validate` exits 3 with a specific message.

| Test | Location | Verifies |
|---|---|---|
| `test_free_tier_ac4_validation` | `tests/unit/config/test_free_tier_rules.py` | |

### AC5 — Changes allowed and refused
**Given** a free-tier cluster, **then** `cluster update NAME --description …` sends `PUT …/clusters/freeTier/{id}`; `cluster scale` and `cluster update --cpu/--support-plan` exit 4 with `free-tier clusters have 1 node and fixed size; create a provisioned cluster for that`.

| Test | Location | Verifies |
|---|---|---|
| `test_free_tier_ac5_update_description` | `tests/scenario/test_free_tier.py` | |
| `test_free_tier_ac5_scale_refused` | same | |

### AC6 — Import and sync understand free tier
**Given** a free-tier cluster in Capella, **then** `import`/`sync` write it as `tier: free` with its `id`, and a plan afterwards reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_free_tier_ac6_import_round_trip` | `tests/scenario/test_free_tier.py` | |

## Out of scope
- Free-tier buckets (`…/buckets/freeTier`) and free-tier App Services.
- Deleting free-tier clusters (CAP-014 covers deletion).

## Open questions
- Does `GET …/clusters` (list) include free-tier clusters? capellactl handles both: it records the free-tier cluster's `id` and reads it through `GET …/clusters/freeTier/{id}`.
- Is the "one free-tier cluster" limit per organization or per user? The tool checks the whole organization (the stricter reading).

## Implementation notes (as built)
- Free-tier facts come from the spec text of `POST …/clusters/freeTier` (1 node, data/index/query/search, one per tenant, 9 fixed regions, configurable fields, features not included). They live in `capellactl/config/crossref.py` (`FREE_TIER_REGIONS`) and `cluster_ops.py`, so they are easy to update if Capella changes them.
- The Management API has no catalog endpoint for providers, regions, sizes or versions per organization. `cluster options` is honest about that: provisioned regions are free text with suggestions from the regions already in use, and Capella's own 422 message is shown for anything it does not offer.
- Free-tier availability is checked across every project of the organization and in capella.yaml; the stricter "per organization" reading of "one per tenant" is used.
- A free-tier cluster is always recorded with its `id` and read through `GET …/clusters/freeTier/{id}` when the cluster list does not include it, so it works whichever way the list behaves (open question).
- Found while building: the loader added the default `configurationType: multiNode` to free-tier entries, which the free-tier rule then rejected; defaults now apply to provisioned clusters only.
- Import skips the schedule and bucket reads for free-tier clusters (no on/off schedule; free-tier buckets use separate endpoints, out of scope).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_options_ac1_free_tier_available` (tests/scenario/test_free_tier.py)<br>`test_options_ac1_free_tier_used` (tests/scenario/test_free_tier.py) |
| AC2 | `test_free_tier_ac2_create_and_record` (tests/scenario/test_free_tier.py) |
| AC3 | `test_free_tier_ac3_interactive_choices` (tests/scenario/test_free_tier.py)<br>`test_free_tier_ac3_not_offered_when_used` (tests/scenario/test_free_tier.py) |
| AC4 | `test_free_tier_ac4_validation` (tests/unit/config/test_free_tier_rules.py) |
| AC5 | `test_free_tier_ac5_update_description` (tests/scenario/test_free_tier.py)<br>`test_free_tier_ac5_scale_refused` (tests/scenario/test_free_tier.py) |
| AC6 | `test_free_tier_ac6_import_round_trip` (tests/scenario/test_free_tier.py) |
