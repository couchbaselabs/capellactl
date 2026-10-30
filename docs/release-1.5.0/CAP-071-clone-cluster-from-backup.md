# CAP-071 — Create a cluster from a snapshot backup

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E12 Replication & cluster operations | P1 | 3 | CAP-057, CAP-049 | Not started |

## User story
As an **operator**, I want to create a new cluster from a cluster's cloud snapshot backup, so that I can stand up a
copy for testing or recover into another region without touching the original cluster.

## Context & discovery
- `POST …/projects/{projectId}/cloudsnapshotbackups/{backupId}/clone` → 202 with `restoreId` and `clusterId`.
  Body: `name` (required), `description`, `cloudProvider` (`type`, `region`, `cidr`), `availability.type`
  (`single`, `multi`), `support` (`plan`, `timezone`), `zones`.
- CAP-057 restores a backup into its own cluster and listed "clone" as out of scope; CAP-049 copies a cluster's
  layout without its data. This story copies the data.

## Design
```
capellactl cluster backup clone SOURCE_CLUSTER BACKUP_ID NEW_NAME [--region R] [--cidr CIDR] [--availability single|multi] [--support-plan P] [--timezone TZ]
```
Example:
```
capellactl cluster backup clone nova-prod-01 7f3c… nova-restore-01 --region us-west-2
```
- Defaults come from the source cluster (provider, availability, support); `--region` defaults to the source region.
  The CIDR is picked as in CAP-049 when not given.
- The new cluster is added to capella.yaml (CAP-038 flow) with the source's layout, then the command waits for the
  restore through `cluster backup restores` until it completes (`--no-wait` returns after the 202).
- Code: `cli/cluster_backup.py` gains `clone`; one operation in `api/endpoints.py`; the fake creates the cluster.

## Acceptance criteria & tests

### AC1 — Clone
**Given** a completed backup, **then** one `POST …/clone` with `name: nova-restore-01` and the source's provider and
region, a wait until the new cluster is healthy and the restore complete, and the new cluster in capella.yaml.

| Test | Location | Verifies |
|---|---|---|
| `test_backup_clone_ac1_clone` | `tests/scenario/test_cluster_backup_clone.py` | Body, wait, file |

### AC2 — Validation
**Given** a name already used in the project, a backup that is not complete, a region the provider does not offer,
or a CIDR that overlaps another cluster's, **then** exit 3 or 4 with the reason and zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_backup_clone_ac2_refused` | `tests/scenario/test_cluster_backup_clone.py` | Parametrised |

### AC3 — Idempotent re-run
**Given** AC1 completed, **then** re-running prints `cluster nova-restore-01 already exists`, exit 0, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_backup_clone_ac3_rerun_noop` | `tests/scenario/test_cluster_backup_clone.py` | |

### AC4 — Discoverable
**Given** `cluster backup clone --help` and `help backup`, **then** the example above is shown and the difference
between restore, clone and `cluster clone` is explained.

| Test | Location | Verifies |
|---|---|---|
| `test_backup_clone_ac4_help` | `tests/scenario/test_cluster_backup_clone.py` | |

## Out of scope
- Cloning into another project (the endpoint is project-scoped).

## Open questions
- Are buckets, scopes and credentials of the source copied by the restore, so `sync` should write them for the new
  cluster? Assumed yes for data; credentials to be checked.
