# CAP-013 — Deletion protection

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E3 Clusters | P0 | 2 | CAP-011 | Implemented |

## User story
As an **operator**, I want production clusters protected from deletion, declared in the config file, so that neither the tool nor a person can delete the cluster or its buckets by mistake.

## Context & discovery
- `PUT …/clusters/{clusterId}/deletionProtection` body `{deletionProtection*: boolean}` → `204`.
- Per the spec: when enabled, *the cluster, its app service, and its buckets cannot be deleted, and bucket data cannot be flushed*.
- Current value is the `deletionProtection` field of `GET …/clusters/{clusterId}`.

## Implementation details
- Config: `clusters[].deletionProtection: true|false` (omit = leave unchanged).
- `resources/deletion_protection.py`: reconciled after the cluster is `healthy`.
- Shared guard `guards.deletion_protected(cluster)` used by cluster delete, bucket delete, `destroy`, `--prune`, project `--cascade`.
- CLI: `capellactl cluster protect NAME --on|--off`.

## Acceptance criteria & tests

### AC1 — Enable from config
**Given** `deletionProtection: true` and Capella shows `false`, **then** `~ cluster nova-dev-01  deletionProtection: false → true` and `PUT …/deletionProtection {"deletionProtection": true}`.

| Test | Location | Verifies |
|---|---|---|
| `test_protection_ac1_enable_from_config` | `tests/scenario/test_deletion_protection.py` | |
| `test_endpoints_ac1_deletion_protection_contract` | `tests/contract/test_endpoints_cluster.py` | |

### AC2 — Applied after create
**Given** a new cluster with `deletionProtection: true`, **then** the protection `PUT` happens after the cluster reaches `healthy` and before buckets are created.

| Test | Location | Verifies |
|---|---|---|
| `test_protection_ac2_after_create_before_buckets` | `tests/scenario/test_deletion_protection.py` | |

### AC3 — Omitted means unchanged
**Given** no `deletionProtection` key, **then** no protection change is planned regardless of current value.

| Test | Location | Verifies |
|---|---|---|
| `test_protection_ac3_omitted_unchanged` | `tests/unit/resources/test_deletion_protection.py` | |

### AC4 — Protection blocks deletes before any API call
**Given** protection is on, **then** `cluster delete`, `bucket delete`, `destroy`, `apply --prune` (for buckets) and `project delete --cascade` each print `deletion protection is on for nova-dev-01; run 'capellactl cluster protect nova-dev-01 --off' first`, exit 4, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_protection_ac4_blocks_all_delete_paths` | `tests/scenario/test_deletion_protection.py` | Parametrised over 5 commands |

### AC5 — Ad-hoc command
**Given** `cluster protect nova-dev-01 --on`, **then** the `PUT` is sent and capella.yaml records `deletionProtection: true` for the cluster (`.bak` kept), so a later `apply` keeps it on and `sync` finds nothing to change. **Given** `--off`, **then** the key is removed from the file (as `import` writes an unprotected cluster). Running it when Capella already has that value makes zero writes, and still records it in the file if the file said otherwise. *(Revised 2026-10-07: it used to change Capella only and print a drift note, leaving the user to reconcile the file.)*

| Test | Location | Verifies |
|---|---|---|
| `test_protection_cli_ac5_off_records_in_file` | `tests/scenario/test_deletion_protection.py` | |
| `test_protection_cli_ac5_on_records_in_file` | same | `apply` and `sync` then report no changes |
| `test_protection_cli_ac5_already_off_noop` | same | |

### AC6 — Idempotent re-run
**Given** AC1 applied, **then** a re-run has zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_protection_ac6_rerun_zero_writes` | `tests/scenario/test_deletion_protection.py` | |

## Out of scope
- Bucket flush (not exposed in 1.0.0).

## Open questions
- None.

## Implementation notes (as built)

- `resources/deletion_protection.py` (`DeletionProtectionReconciler`, kind `deletion-protection`) is the cluster's first child, so it runs after the cluster is healthy and before allowed CIDRs and buckets. The current value is read from the cluster's own `GET`/list body: planning makes no extra request.
- **AC1 (deviation)**: the plan line reads `~ deletion-protection nova-dev-01` with the change `deletionProtection:  false → true` on the next line, not `~ cluster nova-dev-01  deletionProtection: false → true`. Keeping it a separate kind keeps `--target`, the apply summary and JSON output one-resource-per-line.
- **AC2**: for a new cluster, `deletionProtection: true` plans as `+ deletion-protection nova-dev-01  deletionProtection: true  (after cluster is healthy)`; `false` plans nothing visible (Capella creates clusters unprotected). After the `PUT`, the cluster's observed body is updated, so later delete guards in the same run see the new value.
- **AC4**: the shared guard is `resources/guards.py` (`deletion_protected`, `protection_message`), used by `cluster delete`, `bucket delete`, `apply --prune` (buckets), `project delete --cascade` and `destroy`. `destroy` itself ships with CAP-030; until then it already runs the protection check first (exit 4, zero writes) and only then reports that it is not available.
- **AC5**: `capellactl cluster protect NAME --on|--off [--project NAME]` changes Capella and records the value in `capella.yaml` (revised 2026-10-07, see AC5; before, it changed Capella only, so the next `apply` reverted it). `--on` needs no confirmation; `--off` asks (or needs `--auto-approve` without a terminal). When the file declares the opposite value it prints the drift note.
- Tests: AC1 `tests/scenario/test_deletion_protection.py::test_protection_ac1_enable_from_config`, `tests/unit/resources/test_deletion_protection.py::test_protection_ac1_diff`, `tests/contract/test_endpoints_cluster.py::test_endpoints_ac1_deletion_protection_contract`; AC2 `test_protection_ac2_after_create_before_buckets`, `test_protection_ac2_new_cluster`; AC3 `test_protection_ac3_omitted_unchanged` (unit) and `test_protection_ac3_omitted_unchanged_plan` (scenario); AC4 `test_protection_ac4_blocks_all_delete_paths` (5 commands); AC5 `test_protection_cli_ac5_off_records_in_file`, `test_protection_cli_ac5_on_records_in_file`, `test_protection_cli_ac5_already_off_noop`, `test_protection_cli_ac5_on_and_confirmation`; AC6 `test_protection_ac6_rerun_zero_writes`.
