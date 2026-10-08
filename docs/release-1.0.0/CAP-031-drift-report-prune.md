# CAP-031 — Drift report & prune

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P1 | 3 | CAP-030 | Implemented |

## User story
As an **operator**, I want to see what differs between Capella and my file, including resources someone created by hand, and optionally remove them, so that environments stay clean and auditable.

## Context & discovery
- The planner already computes changed and missing resources; drift adds **unmanaged** ones: present in Capella under the managed project/clusters but not in the file.
- Unmanaged kinds: clusters, allowed CIDRs, buckets, non-system scopes and collections, credentials, hibernation schedules.

## Implementation details
```
capellactl drift [--detailed-exitcode] [-o json]
capellactl apply --prune
```
Output groups: `Changed`, `Missing`, `Unmanaged`. `--prune` adds `-` actions for unmanaged CIDRs, buckets, scopes, collections, credentials and schedules — never clusters or the project.

## Acceptance criteria & tests

### AC1 — Three groups
**Given** one changed bucket, one missing collection and one hand-made credential `temp_admin`, **then** `drift` prints each under its group, makes only `GET`s, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_drift_ac1_three_groups` | `tests/scenario/test_drift.py` | `fake.writes() == []` |

### AC2 — CI-friendly exit code and JSON
**Given** any drift and `--detailed-exitcode`, **then** exit 2; no drift → 0. `-o json` has `changed`, `missing`, `unmanaged` arrays.

| Test | Location | Verifies |
|---|---|---|
| `test_drift_ac2_exit_code_and_json` | `tests/scenario/test_drift.py` | |

### AC3 — Prune deletes unmanaged children only
**Given** `apply --prune` with unmanaged credential, CIDR and cluster, **then** the credential and CIDR get `-` actions; the cluster is listed as `unmanaged (not pruned: clusters are never pruned)`.

| Test | Location | Verifies |
|---|---|---|
| `test_prune_ac3_children_only` | `tests/scenario/test_drift.py` | |

### AC4 — Prune respects protection and confirmation
**Given** an unmanaged bucket on a protected cluster, **then** `--prune` blocks it (exit 4). **Given** no protection, **then** the bucket's typed confirmation (CAP-024 AC1) is required unless `--auto-approve`.

| Test | Location | Verifies |
|---|---|---|
| `test_prune_ac4_protection_and_confirmation` | `tests/scenario/test_drift.py` | |

### AC5 — System objects never unmanaged
**Given** `_default` and `_system` scopes, **then** they never appear in `Unmanaged`.

| Test | Location | Verifies |
|---|---|---|
| `test_drift_ac5_system_objects_excluded` | `tests/scenario/test_drift.py` | |

## Out of scope
- Adding unmanaged resources to an existing file. `capellactl import` (CAP-036) writes a new file from Capella; merging into an existing file is a candidate for 1.1.

## Open questions
- None.

## Implementation notes (as built)
- `capellactl drift [--detailed-exitcode] [-o json]` (`cli/env.py`): one read-only plan with every undeclared resource of a prunable kind, plus undeclared clusters (`Reconciler.listed_when_asked`), printed as *Changed*, *Missing* and *Unmanaged*; JSON has `changed`, `missing` (plan actions) and `unmanaged` (labels).
- `apply --prune` deletes unmanaged CIDRs, buckets, scopes, collections, credentials and schedules (schedules since CAP-020); clusters are listed as `cluster NAME  (not pruned: clusters are never pruned)`; projects are never pruned.
- AC4: a bucket on a protected cluster is BLOCKED (CAP-024); without protection the typed bucket-name confirmation is asked unless `--auto-approve`.
- `apply` with nothing to change still lists unmanaged resources it found.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_drift_ac1_three_groups` (tests/scenario/test_drift.py) |
| AC2 | `test_drift_ac2_exit_code_and_json` (tests/scenario/test_drift.py) |
| AC3 | `test_prune_ac3_children_only` (tests/scenario/test_drift.py) |
| AC4 | `test_prune_ac4_protection_and_confirmation` (tests/scenario/test_drift.py) |
| AC5 | `test_drift_ac5_system_objects_excluded` (tests/scenario/test_drift.py) |

