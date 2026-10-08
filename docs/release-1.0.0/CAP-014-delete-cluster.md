# CAP-014 — Delete cluster

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E3 Clusters | P0 | 3 | CAP-013 | Implemented |

## User story
As an **operator**, I want to delete a cluster safely and wait until it is gone, so that teardown scripts can rely on it having been removed.

## Context & discovery
- `DELETE …/clusters/{clusterId}` → `202`; query parameter `retainsnapshotbackups` (boolean).
- Completion: `GET` returns `404`. Failure state: `destroyFailed`. Transitional: `destroying`.

## Implementation details
`capellactl cluster delete NAME [--discard-snapshots] [--cascade] [--auto-approve]`.
- Default sends `retainsnapshotbackups=true`; `--discard-snapshots` sends `false` and adds a red warning to the confirmation.
- Confirmation shows name, provider/region, node count, bucket count and requires typing the cluster name.

## Acceptance criteria & tests

### AC1 — Delete and wait
**Given** `nova-dev-01` exists without protection, **when** deletion is confirmed, **then** `DELETE …/clusters/{id}?retainsnapshotbackups=true` is sent and the command waits until `404`, then prints `deleted cluster nova-dev-01 (snapshot backups retained)`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_delete_ac1_delete_and_wait` | `tests/scenario/test_cluster_delete.py` | |
| `test_endpoints_ac1_delete_cluster_query_param` | `tests/contract/test_endpoints_cluster.py` | |

### AC2 — Discard snapshots
**Given** `--discard-snapshots`, **then** `retainsnapshotbackups=false` and the confirmation includes `snapshot backups will be deleted`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_delete_ac2_discard_snapshots` | `tests/scenario/test_cluster_delete.py` | |

### AC3 — Guards
**Given** deletion protection on, **then** exit 4 (CAP-013). **Given** two clusters with that name, **then** exit 4 (ambiguous). **Given** the cluster has buckets and no `--cascade`, **then** the confirmation lists them (Capella deletes them with the cluster); the delete is not blocked.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_delete_ac3_protected_blocked` | `tests/scenario/test_cluster_delete.py` | |
| `test_cluster_delete_ac3_ambiguous_blocked` | same | |
| `test_cluster_delete_ac3_lists_buckets_in_confirmation` | same | |

### AC4 — Already destroying, already gone
**Given** the cluster is `destroying`, **then** the command waits and sends no `DELETE`. **Given** it does not exist, **then** `not found, nothing to do`, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_delete_ac4_destroying_waits_only` | `tests/scenario/test_cluster_delete.py` | |
| `test_cluster_delete_ac4_absent_noop` | same | |

### AC5 — Destroy failure
**Given** the cluster enters `destroyFailed`, **then** exit 1 with the activity-log hint.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_delete_ac5_destroy_failed` | `tests/scenario/test_cluster_delete.py` | |

### AC6 — Hibernation schedule shown in confirmation
**Given** the cluster has an on/off schedule, **then** the confirmation mentions it, and the delete proceeds (the schedule is deleted with the cluster); no separate schedule `DELETE` is required.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_delete_ac6_mentions_schedule` | `tests/scenario/test_cluster_delete.py` | |

### AC7 — Idempotent re-run
**Given** AC1 completed, **then** a re-run prints `not found, nothing to do`, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_delete_ac7_rerun_noop` | `tests/scenario/test_cluster_delete.py` | |
| `test_cluster_delete_ac7_integration` | `tests/integration/test_cluster_lifecycle.py` | |

## Out of scope
- Deleting linked App Services separately.

## Open questions
- Can a `turnedOff` cluster be deleted directly, or must it be turned on first? Confirm in sandbox; if not, the command should offer `--power-on`.
- Does a schedule on the cluster need deleting before cluster deletion? (AC6 assumes not; confirm.)

## Implementation notes (as built)

- `capellactl cluster delete NAME [--discard-snapshots] [--cascade] [--project NAME]` (`cli/cluster_lifecycle.py`). The confirmation shows `- cluster NAME  provider region · N nodes · M buckets`, the bucket names, the hibernation schedule when there is one, and the snapshot-backup line (red `WARNING: snapshot backups will be deleted` with `--discard-snapshots`), then asks for the cluster name to be typed. `--auto-approve` skips the prompt; without a terminal the command refuses.
- After the cluster is gone the command **removes it from `capella.yaml`** (keeping a `.bak`), like `bucket delete` and `project delete`, so the next `apply` does not deploy it again. With `--no-wait` the file is kept; re-running the command waits (AC4) and then removes it.
- A cluster pinned with `id:` in the file is matched by id (free-tier clusters are read with their own endpoint when the list does not include them); free-tier clusters are deleted through `DELETE …/clusters/freeTier/{id}` and have no snapshot backups.
- `--cascade` changes nothing: Capella always deletes the cluster's buckets, schedule and allowed CIDRs with it, and they are listed before you confirm (AC3). It is accepted for symmetry with `project delete --cascade`.
- **AC5**: a `destroyFailed` state exits 1 with `cluster NAME entered destroyFailed; check the Capella UI activity log`; a timeout exits 5. The fake harness gained `FakeCapella.fail_destroy(cluster_id)`.
- Open questions remain open (deleting a `turnedOff` cluster; schedule deletion): the command does not block either case, and the nightly integration test will show Capella's behaviour.
- Tests (`tests/scenario/test_cluster_delete.py` unless noted): AC1 `test_cluster_delete_ac1_delete_and_wait`, `test_cluster_delete_ac1_wrong_name_cancels`, `test_cluster_delete_no_wait_then_rerun_waits`, `tests/contract/test_endpoints_cluster.py::test_endpoints_ac1_delete_cluster_query_param`; AC2 `test_cluster_delete_ac2_discard_snapshots`; AC3 `test_cluster_delete_ac3_protected_blocked`, `test_cluster_delete_ac3_ambiguous_blocked`, `test_cluster_delete_ac3_lists_buckets_in_confirmation`; AC4 `test_cluster_delete_ac4_destroying_waits_only`, `test_cluster_delete_ac4_absent_noop`; AC5 `test_cluster_delete_ac5_destroy_failed`; AC6 `test_cluster_delete_ac6_mentions_schedule`; AC7 `test_cluster_delete_ac7_rerun_noop`, `tests/integration/test_cluster_lifecycle.py::test_cluster_delete_ac7_integration`.
