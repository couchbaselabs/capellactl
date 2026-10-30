# CAP-070 — XDCR replications as code

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E12 Replication & cluster operations | P0 | 8 | CAP-025, CAP-040 | Not started |

## User story
As an **operator**, I want to declare cross-datacenter replications between my clusters in capella.yaml and pause or
resume them from the CLI, so that disaster-recovery and multi-region copies are set up the same way every time.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| List (cluster) | `GET …/clusters/{clusterId}/replications` | 200 | `id`, `sourceCluster`, `targetCluster`, `status`, `direction` |
| List (project) | `GET …/projects/{projectId}/replications` | 200 | Same, across the project |
| Create | `POST …/clusters/{clusterId}/replications` | 201 / 202 | `sourceBucket`, `target` (`cluster`, `bucket`, `type` `capella`/`external`), `mode` (`async`, `sync`), `mappings[]`, `direction` (`oneWay`, `twoWay`), `priority`, `networkUsageLimit`, `filter`. 201 → `replicationId`, `reverseReplicationId`; 202 → `jobId` |
| Get | `GET …/replications/{replicationId}` | 200 | `status` (`pending`, `pausing`, `failed`, `paused`, `running`), `changesLeft`, `error`, `source`, `target`, `mappings` |
| Update | `PUT …/replications/{replicationId}` | 204 | `priority`, `networkUsageLimit`, `filter`, `allScopes`, `mappings` |
| Delete | `DELETE …/replications/{replicationId}` | 204 | |
| Pause | `DELETE …/replications/{replicationId}/activationStatus` | 204 | |
| Resume | `POST …/replications/{replicationId}/activationStatus` | 204 | |
| Job | `GET …/replications/jobs/{jobId}` | 200 | `state` (`pending`, `processing`, `complete`, `failed`, …), `replicationId` |

The source and target buckets need compatible conflict resolution; a replication has no name in the API, so its
identity in capellactl is `sourceCluster/sourceBucket → targetCluster/targetBucket`.

## Design

### Commands
```
capellactl replication list   [CLUSTER] [--project NAME]
capellactl replication get    CLUSTER ID
capellactl replication create CLUSTER --bucket B --to CLUSTER/BUCKET [--two-way] [--map SRC_SCOPE[.COLL]=DST_SCOPE[.COLL] …] [--priority low|medium|high] [--limit-mbps N]
capellactl replication update CLUSTER ID [--priority …] [--limit-mbps N] [--map …]
capellactl replication delete CLUSTER ID
capellactl replication pause  CLUSTER ID
capellactl replication resume CLUSTER ID
capellactl replication job    CLUSTER JOB_ID
```
Example:
```
capellactl replication create nova-prod-01 --bucket orders --to nova-dr-01/orders
capellactl replication list nova-prod-01
```

### capella.yaml
```yaml
clusters:
  - name: nova-prod-01
    replications:
      - bucket: orders
        to: nova-dr-01/orders          # cluster/bucket in this file (any project, CAP-040)
        direction: oneWay
        priority: medium
        paused: false
        mappings:                       # optional; all scopes when omitted
          - {from: sales, to: sales}
```
- Replications reconcile after both buckets exist, and are deleted before either bucket or cluster.
- A `202` create is followed through `replication job` until `complete` (CAP-007 waiter).
- `mode`, `direction` and the buckets are immutable: a change is shown as BLOCKED (exit 4) with "delete and recreate".
- Code: `cli/replication_cmds.py`, `resources/replication.py` (prunable), nine operations, fake Capella.

## Acceptance criteria & tests

### AC1 — Create from capella.yaml
**Given** the block above and both buckets, **then** `apply` sends one `POST` with `sourceBucket` (ID),
`target.cluster` (ID), `target.bucket` (ID) and `direction: oneWay`, and `plan` then reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_replication_ac1_apply_create` | `tests/scenario/test_replications.py` | |
| `test_replication_ac1_async_job_followed` | same | 202 + job |

### AC2 — Idempotent
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_replication_ac2_rerun_zero_writes` | `tests/scenario/test_replications.py` | |

### AC3 — Validation
**Given** a target bucket that does not exist, a replication to the same bucket, mismatched conflict resolution, or a
mapping to an undeclared scope, **then** exit 3 before any write.

| Test | Location | Verifies |
|---|---|---|
| `test_replication_ac3_validation` | `tests/unit/config/test_replication_rules.py` | Parametrised |

### AC4 — Update, pause, resume
**Given** `priority` changed, **then** one `PUT`. **Given** `paused: true` or `replication pause`, **then**
`DELETE …/activationStatus` and the status is `paused`; `resume` reverses it. An immutable change is BLOCKED.

| Test | Location | Verifies |
|---|---|---|
| `test_replication_ac4_update_pause_resume` | `tests/scenario/test_replications.py` | |
| `test_replication_ac4_immutable_blocked` | same | |

### AC5 — Delete ordering
**Given** `destroy` or a bucket deletion with a replication from or to it, **then** the replication is deleted first;
`bucket delete` lists the replications it removes in the confirmation.

| Test | Location | Verifies |
|---|---|---|
| `test_replication_ac5_delete_order` | `tests/scenario/test_replications.py` | |

### AC6 — Lists, sync, drift
**Given** replications, **then** `list` prints `S.NO`, `SOURCE`, `TARGET`, `DIRECTION`, `STATUS`, `ID`; `sync`
writes them; `drift` lists unmanaged ones and `apply --prune` deletes them.

| Test | Location | Verifies |
|---|---|---|
| `test_replication_ac6_list_sync_drift` | `tests/scenario/test_replications.py` | |

## Out of scope
- Replications to `external` (non-Capella) targets; the file has no way to name them yet.

## Open questions
- When is a create answered with 202 and a job rather than 201? Recorded from the sandbox before AC1 is coded.
