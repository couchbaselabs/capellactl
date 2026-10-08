# CAP-022 — Ensure allowed CIDRs (IP allowlist)

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E6 Network access | P0 | 3 | CAP-011 | Implemented |

## User story
As an **operator**, I want the cluster's allowed IP ranges declared in the config file, so that network access is reviewed, repeatable and easy to audit.

## Context & discovery

| Operation | Endpoint | Success |
|---|---|---|
| List | `GET …/clusters/{clusterId}/allowedcidrs` | 200 |
| Get | `GET …/allowedcidrs/{allowedCidrId}` | 200 |
| Create | `POST …/clusters/{clusterId}/allowedcidrs` | 201 `{id}`; body `cidr*`, `comment`, `expiresAt` (RFC 3339; omitted = permanent) |
| Delete | `DELETE …/allowedcidrs/{allowedCidrId}` | 204 |

From the spec: *"updating this resource is not supported; you must delete and recreate allowed CIDRs instead. As a result, ETags are also not supported."*

## Implementation details
```yaml
allowedCidrs:
  - cidr: 203.0.113.10/32
    comment: Office VPN egress
  - cidr: 198.51.100.0/24
    comment: CI runners
    expiresAt: "2026-12-31T23:59:59Z"
# allowAnyIp: true     # required to permit 0.0.0.0/0
```
- Key: canonical CIDR (`ipaddress.ip_network(strict=True)`); a bare IP becomes `/32`.
- Change to `comment`/`expiresAt` → `REPLACE` (create new first, then delete old; fall back to delete-then-create if the duplicate create is rejected).
- CLI: `cidr list CLUSTER`, `cidr create CLUSTER CIDR`, `cidr delete CLUSTER CIDR` (no update: a CIDR is immutable; 00-architecture.md section 5 "Verbs").

## Acceptance criteria & tests

### AC1 — Create missing entries
**Given** two CIDRs in the file and none on the cluster, **then** two `+ allowed-cidr` lines and two `POST`s with `{cidr, comment[, expiresAt]}` (empty fields omitted).

| Test | Location | Verifies |
|---|---|---|
| `test_cidr_ac1_create_missing` | `tests/scenario/test_allowed_cidrs.py` | |
| `test_endpoints_ac1_allowed_cidr_contract` | `tests/contract/test_endpoints_cidr.py` | |

### AC2 — Normalisation
**Given** `203.0.113.10` in the file and `203.0.113.10/32` on the cluster, **then** `=`. **Given** `10.0.0.5/24` (host bits set), **then** `validate` exits 3 `10.0.0.5/24 is not a network address (did you mean 10.0.0.0/24?)`.

| Test | Location | Verifies |
|---|---|---|
| `test_cidr_normalize_ac2_bare_ip_is_32` | `tests/unit/resources/test_allowed_cidr.py` | |
| `test_cidr_validate_ac2_host_bits_rejected` | `tests/unit/config/test_cidr_rules.py` | |

### AC3 — Replace on comment/expiry change
**Given** the same CIDR with a different `comment`, **then** `± allowed-cidr … comment: "a" → "b"  (replace: API has no update)` and the writes are `POST` (new) then `DELETE` (old). **Given** the `POST` returns `409`, **then** the writes become `DELETE` then `POST` with warning `access from 203.0.113.10/32 is briefly interrupted`.

| Test | Location | Verifies |
|---|---|---|
| `test_cidr_ac3_replace_create_then_delete` | `tests/scenario/test_allowed_cidrs.py` | Write order |
| `test_cidr_ac3_replace_fallback_on_409` | same | |

### AC4 — Unmanaged entries left alone
**Given** a CIDR on the cluster that is not in the file, **then** `plan` lists it under `Unmanaged (not in capella.yaml; use --prune to delete)` and no write happens without `--prune`.

| Test | Location | Verifies |
|---|---|---|
| `test_cidr_ac4_unmanaged_not_deleted` | `tests/scenario/test_allowed_cidrs.py` | |

### AC5 — Open-to-the-world guard
**Given** `0.0.0.0/0` without `allowAnyIp: true`, **then** `validate` exits 3. **With** it, **then** `plan` prints a warning line.

| Test | Location | Verifies |
|---|---|---|
| `test_cidr_validate_ac5_any_ip_requires_flag` | `tests/unit/config/test_cidr_rules.py` | |
| `test_cidr_ac5_any_ip_warning` | `tests/scenario/test_allowed_cidrs.py` | |

### AC6 — Expired entries
**Given** an entry in the file whose `expiresAt` is in the past, **then** `validate` warns `expiresAt is in the past; Capella will remove it`, and `plan` treats a missing (expired) entry as `+` only if `expiresAt` is in the future.

| Test | Location | Verifies |
|---|---|---|
| `test_cidr_ac6_past_expiry_warning_and_no_recreate` | `tests/scenario/test_allowed_cidrs.py` | `freezegun` |

### AC7 — Ad-hoc delete
**Given** `cidr delete nova-dev-01 203.0.113.10/32`, **then** the matching entry is deleted; absent → exit 0 `not found, nothing to do`.

| Test | Location | Verifies |
|---|---|---|
| `test_cidr_cli_ac7_delete_and_absent` | `tests/scenario/test_allowed_cidrs.py` | |

### AC8 — Idempotent re-run
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_cidr_ac8_rerun_zero_writes` | `tests/scenario/test_allowed_cidrs.py` | |

## Out of scope
- App Service allowed CIDRs; API key allowed CIDRs.

## Open questions
- Does Capella reject a duplicate CIDR with `409` (assumed in AC3), or accept it? Confirm in sandbox.

## Implementation notes (as built)

- `resources/allowed_cidr.py` (`AllowedCidrReconciler`, kind `allowed-cidr`, key `CLUSTER/CANONICAL-CIDR`) replaces the deferred placeholder. Matching uses the canonical CIDR (`normalize_cidr`; a bare IP is `/32`, or `/128` for IPv6). `comment` and `expiresAt` are compared as the file states them: an omitted comment means none and an omitted `expiresAt` means permanent; times are compared as instants, so `…Z` and `….000+00:00` are equal.
- **AC3**: `±` lines read `± allowed-cidr nova-dev-01/203.0.113.10/32  (replace: API has no update)` with the field changes on the following lines; REPLACE counts as "to add" in the summary. Whether Capella rejects a duplicate CIDR with 409 is still open; both orders are implemented and tested (`FakeCapella.cidr_duplicates_allowed` selects the behaviour).
- **AC4**: new engine support, usable by other kinds: `Reconciler.reports_unmanaged` / `unmanaged_label`, `Plan.unmanaged` (also in `-o json` as `plan.unmanaged`), printed under `Unmanaged (not in capella.yaml; use --prune to delete):`. Allowed CIDRs are observed for every existing cluster, also when the file declares none, so unmanaged entries are always listed; listing them is not a change (`--detailed-exitcode` stays 0). `apply --prune` deletes them (no typed confirmation, unlike buckets).
- **AC5**: the `0.0.0.0/0` / `::/0` rule existed in `config/crossref.py`; it now also applies to free-tier clusters. With `allowAnyIp: true` the plan prints `warning: allowed CIDR 0.0.0.0/0 on CLUSTER lets any IP address connect (allowAnyIp: true)`.
- **AC6**: every command that loads the file prints `warning: PATH: expiresAt is in the past; Capella will remove it (line N)` (`crossref.config_warnings`). `validate` also rejects an `expiresAt` that is not RFC 3339. In the plan, a missing entry with a past `expiresAt` is `=` with `(expiresAt is in the past; Capella removed it, not re-created)`.
- **CLI**: `cidr list CLUSTER`, `cidr create CLUSTER CIDR [--comment] [--expires-at] [--allow-any-ip] [--no-apply]` (records it in `capella.yaml` and applies it, like `bucket create`) and `cidr delete CLUSTER CIDR` (asks y/N, deletes, removes it from the file). The test-only stub tree now uses the real reconciler.
- Tests: AC1 `tests/scenario/test_allowed_cidrs.py::test_cidr_ac1_create_missing`, `test_cidr_cli_ac1_create_records_and_applies`, `tests/unit/resources/test_allowed_cidr.py::test_cidr_ac1_create_body_omits_empty_fields`, `tests/contract/test_endpoints_cidr.py::test_endpoints_ac1_allowed_cidr_contract`; AC2 `test_cidr_normalize_ac2_bare_ip_is_32`, `tests/unit/config/test_cidr_rules.py::test_cidr_validate_ac2_host_bits_rejected`, `test_cidr_validate_ac2_cli_exit_3`, `test_cidr_ac2_bare_ip_matches_32`; AC3 `test_cidr_ac3_replace_create_then_delete`, `test_cidr_ac3_replace_fallback_on_409`, `test_cidr_ac3_changes_compare_comment_and_expiry`; AC4 `test_cidr_ac4_unmanaged_not_deleted`, `test_cidr_ac4_unmanaged_listed_when_file_has_none`; AC5 `test_cidr_validate_ac5_any_ip_requires_flag`, `test_cidr_ac5_any_ip_warning`; AC6 `test_cidr_ac6_past_expiry_warning_and_no_recreate` (freezegun), `test_cidr_validate_ac6_expires_at_format`; AC7 `test_cidr_cli_ac7_delete_and_absent`; AC8 `test_cidr_ac8_rerun_zero_writes`.
