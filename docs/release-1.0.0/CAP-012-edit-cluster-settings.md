# CAP-012 — Edit cluster settings & immutable-field protection

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E3 Clusters | P0 | 2 | CAP-011 | Implemented |

## User story
As an **operator**, I want to change a cluster's name, description and support plan by editing the file, and be stopped clearly if I change something Capella cannot change in place, so that I never lose a cluster by accident.

## Context & discovery
- `PUT …/clusters/{clusterId}` requires `name*`, `description*`, `support*`, `serviceGroups*` and returns `204`; `412` on stale `If-Match`.
- Fields not in the update body can only be set at create time: `cloudProvider`, `availability`, `configurationType`, `couchbaseServer`, `zones`, `cmekId`, `enablePrivateDNSResolution`.
- Service-group changes (scaling) are covered by CAP-015 to CAP-017; this story owns the shared `PUT` builder.

## Implementation details
- `resources/cluster.py::build_update_body(observed, desired)` → `{name, description, support, serviceGroups}` from observed overlaid with desired ([00-architecture.md §6.4](00-architecture.md#64-full-replacement-updates)).
- Immutable-field diff produces `BLOCKED` with reason `immutable: <field> (requires a new cluster)`.
- Updates wait for `healthy` before and after (CAP-007).

## Acceptance criteria & tests

### AC1 — Update description and support plan
**Given** `description` and `support.plan` (`developer pro` → `enterprise`) differ, **then** the plan shows both field changes and one `PUT` is sent whose body has observed `name` and `serviceGroups` unchanged and the new `description` and `support`, with `If-Match`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_update_ac1_full_body_overlay` | `tests/scenario/test_cluster_update.py` | Exact body |
| `test_build_update_body_ac1_overlay` | `tests/unit/resources/test_cluster_body.py` | |
| `test_cluster_update_ac1_settings_only_note` | `tests/scenario/test_cluster_update.py` | Plan note; wait shows "applying the change" |
| `test_cluster_update_ac1_scaling_keeps_scaling_wording` | same | No note when nodes change |

### AC2 — Fields not in the file are preserved
**Given** the file omits `description` and Capella has `"Prod"`, **then** a `PUT` triggered by another change carries `"description": "Prod"`.

| Test | Location | Verifies |
|---|---|---|
| `test_build_update_body_ac2_preserves_unset_fields` | `tests/unit/resources/test_cluster_body.py` | |

### AC3 — Immutable fields blocked
**Given** a change to any of `cloudProvider.region`, `cloudProvider.type`, `cloudProvider.cidr`, `availability.type`, `configurationType`, `couchbaseServer.version`, `zones`, `cmekId`, `enablePrivateDNSResolution`, **then** `! cluster nova-dev-01  cloudProvider.region: us-east-1 → us-west-2  BLOCKED (immutable; requires a new cluster)`, exit 4, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_update_ac3_immutable_blocked` | `tests/scenario/test_cluster_update.py` | Parametrised over each field |

### AC4 — Waits for healthy before and after
**Given** the cluster is `rebalancing`, **then** the `PUT` is sent only after `healthy`, and apply waits for `healthy` again after it.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_update_ac4_wait_before_and_after` | `tests/scenario/test_cluster_update.py` | |

### AC5 — Concurrent change
**Given** the first `PUT` returns `412`, **then** the cluster is re-read, re-diffed and the `PUT` retried once with the new ETag.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_update_ac5_412_retry` | `tests/scenario/test_cluster_update.py` | |

### AC6 — Rename only with pinned id
**Given** `id:` is pinned and `name` differs, **then** a rename is planned. **Given** no `id:`, a name change in the file means "different cluster" and is planned as `+` (create), with a warning `no cluster named <new>; did you mean to rename <old>? pin id: to rename`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_update_ac6_rename_with_pinned_id` | `tests/scenario/test_cluster_update.py` | |
| `test_cluster_update_ac6_rename_hint_without_id` | same | |

### AC7 — Idempotent re-run
**Given** AC1 applied, **then** a re-run has zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_update_ac7_rerun_zero_writes` | `tests/scenario/test_cluster_update.py` | |

## Out of scope
- Server version upgrades.

## Open questions
- Does changing `support.plan` from `enterprise` down to `developer pro` have restrictions (for example multi-AZ)? Confirm in sandbox.

## Implementation notes (as built)
- 2026-10-07: Capella has no lighter call for description or support changes; the cluster `PUT` starts a cluster job that the Capella UI lists as "scale" ("Deploying database-wide assets") even when no node changes. When an update changes no service group, the plan adds `note: Capella runs a cluster update job for this (shown as "scale" in the Capella UI); nodes do not change` (in JSON: under `notes`), and the wait prints `applying the change (Capella: scaling)` instead of `scaling`.
- AC6 rename hint is shown when exactly one undeclared cluster exists in the project.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_cluster_update_ac1_full_body_overlay` (tests/scenario/test_cluster_update.py)<br>`test_build_update_body_ac1_overlay` (tests/scenario/test_cluster_update.py)<br>`test_cluster_update_ac1_settings_only_note` (tests/scenario/test_cluster_update.py)<br>`test_cluster_update_ac1_scaling_keeps_scaling_wording` (tests/scenario/test_cluster_update.py) |
| AC2 | `test_build_update_body_ac2_preserves_unset_fields` (tests/scenario/test_cluster_update.py) |
| AC3 | `test_cluster_update_ac3_immutable_blocked` (tests/scenario/test_cluster_update.py) |
| AC4 | `test_cluster_update_ac4_wait_before_and_after` (tests/scenario/test_cluster_update.py) |
| AC5 | `test_cluster_update_ac5_412_retry` (tests/scenario/test_cluster_update.py) |
| AC6 | `test_cluster_update_ac6_rename_with_pinned_id` (tests/scenario/test_cluster_update.py)<br>`test_cluster_update_ac6_rename_hint_without_id` (tests/scenario/test_cluster_update.py) |
| AC7 | `test_cluster_update_ac7_rerun_zero_writes` (tests/scenario/test_cluster_update.py) |
