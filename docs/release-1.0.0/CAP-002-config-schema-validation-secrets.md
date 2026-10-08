# CAP-002 — Configuration file: schema, validation & secret references

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P0 | 5 | CAP-001 | Implemented |

## User story
As an **operator**, I want to describe my whole Capella environment in one YAML file that is validated before anything calls Capella, so that mistakes are caught early and the file can be reviewed like code.

## Context & discovery
- Field names mirror the Management API request bodies (for example `memoryAllocationInMb`, `serviceGroups`, `timeToLiveInSeconds`) so the API reference doubles as config reference.
- Enum values come from the OpenAPI spec: `cloudProvider.type` (`aws`, `gcp`, `azure`), `support.plan` (`basic`, `developer pro`, `enterprise`), `support.timezone` (`ET`, `GMT`, `IST`, `PT`), bucket `type`, `storageBackend`, `durabilityLevel`, `evictionPolicy`, `bucketConflictResolution`, disk types per provider, schedule timezones.
- Reference file: [examples/capella.yaml](examples/capella.yaml).

## Implementation details

### Loading pipeline (`config/loader.py`)
1. Read YAML with a line-tracking safe loader.
2. Check `apiVersion == "capellactl/v1"`.
3. Resolve `${VAR}` and `${file:relative/path}` (relative to the config file's directory; trailing newline stripped). Values resolved for any key named `password` are registered with the redactor (CAP-008).
4. Validate against `config/schema.json` (Draft 2020-12).
5. Apply defaults ([00-architecture.md §6.3](00-architecture.md#63-comparison-rules-enginenormalizepy)).
6. Run cross-reference checks (`config/crossref.py`).
7. Build typed `model.py` dataclasses.

### Cross-reference checks
| Check | Error |
|---|---|
| Credential `access.resources.buckets[].name` exists in the same cluster's `buckets`, unless that entry has `external: true` | `clusters[0].databaseCredentials[1].access[0].resources.buckets[0].name: bucket 'ordrs' is not defined in cluster 'nova-dev-01'` |
| Same for scope and collection names | |
| Names unique within parent (projects n/a, clusters, CIDRs, buckets, scopes, collections, credentials) | `duplicate bucket name 'orders'` |
| At least one service group contains `data` | |
| Disk `type` matches `cloudProvider.type` (AWS `gp3`/`io2`; Azure `P6`…`P60`/`Ultra`; GCP `pd-ssd`) | |
| Service-group limits ([00-architecture.md §7.1](00-architecture.md#71-limits-from-the-api-spec)) | |
| `password` must be a secret reference, never a literal | `passwords must be supplied via ${VAR} or ${file:...}` |

### `capellactl validate`
Runs steps 1–7 with **no network access** and prints a resource count summary.

## Acceptance criteria & tests

### AC1 — Schema errors name path and line
**Given** a file with `numOfNodes: 2` in the first service group of a `multiNode` cluster, **when** `capellactl validate` runs, **then** it prints `clusters[0].serviceGroups[0].numOfNodes: must be between 3 and 27 (line 22)` and exits 3.

| Test | Location | Verifies |
|---|---|---|
| `test_loader_ac1_error_has_path_and_line` | `tests/unit/config/test_loader.py` | Parametrised over 10 invalid fixtures in `tests/unit/config/fixtures/invalid/` |
| `test_validate_ac1_exit_code_3` | `tests/scenario/test_validate.py` | |

### AC2 — Secret references
**Given** `password: ${APP_PW}` and `APP_PW` set, **then** the model holds the value. **Given** `APP_PW` unset, **then** the error is `clusters[0].databaseCredentials[0].password: environment variable APP_PW is not set` (exit 3). **Given** `${file:./secrets/pw.txt}` missing, **then** the error names the path. **In no case** does the error contain the secret value.

| Test | Location | Verifies |
|---|---|---|
| `test_loader_ac2_env_reference_resolved` | `tests/unit/config/test_secrets.py` | |
| `test_loader_ac2_unset_env_names_variable` | same | |
| `test_loader_ac2_file_reference_resolved_relative_to_config` | same | |
| `test_loader_ac2_missing_file_names_path` | same | |
| `test_loader_ac2_errors_never_contain_value` | same | `assert_no_secret` |

### AC3 — Literal passwords rejected
**Given** `password: Sup3r$ecret`, **then** validation fails with `passwords must be supplied via ${VAR} or ${file:...}` and the literal is not echoed.

| Test | Location | Verifies |
|---|---|---|
| `test_loader_ac3_literal_password_rejected` | `tests/unit/config/test_secrets.py` | |

### AC4 — Cross-reference checks
**Given** each invalid cross-reference in the table above, **then** a specific error with the YAML path is reported; **given** `external: true` on a bucket reference, **then** no error.

| Test | Location | Verifies |
|---|---|---|
| `test_crossref_ac4_unknown_bucket` | `tests/unit/config/test_crossref.py` | |
| `test_crossref_ac4_unknown_scope_and_collection` | same | |
| `test_crossref_ac4_external_bucket_allowed` | same | |
| `test_crossref_ac4_duplicate_names` | same | Parametrised per kind |
| `test_crossref_ac4_disk_type_matches_provider` | same | |
| `test_crossref_ac4_data_service_required` | same | |

### AC5 — Defaults applied
**Given** a bucket with only `name` and `memoryAllocationInMb`, **then** the model has `type=couchbase, replicas=1, durabilityLevel=none, timeToLiveInSeconds=0, flushEnabled=false, bucketConflictResolution=seqno`. `priority` is **not** defaulted (it depends on the server version), so an omitted priority is never compared (CAP-005 AC3).

| Test | Location | Verifies |
|---|---|---|
| `test_loader_ac5_bucket_defaults` | `tests/unit/config/test_defaults.py` | |
| `test_loader_ac5_cluster_defaults` | same | `configurationType=multiNode` |

### AC6 — Offline validate and summary
**Given** [examples/capella.yaml](examples/capella.yaml) with its env vars set, **when** `capellactl validate` runs with networking disabled, **then** it prints `Configuration valid: 1 project, 1 cluster, 2 buckets, 3 scopes, 4 collections, 3 credentials, 2 allowed CIDRs, 1 hibernation schedule` and exits 0.

| Test | Location | Verifies |
|---|---|---|
| `test_validate_ac6_example_is_valid_offline` | `tests/scenario/test_validate.py` | `socket` patched to raise on connect |

### AC7 — Unknown apiVersion
**Given** `apiVersion: capellactl/v2`, **then** exit 3 with `this file needs capellactl supporting capellactl/v2; installed version supports capellactl/v1`.

| Test | Location | Verifies |
|---|---|---|
| `test_loader_ac7_unknown_api_version` | `tests/unit/config/test_loader.py` | |

## Out of scope
- Multiple projects per file (one file = one project).
- Includes / overlays (`base.yaml` + `prod.yaml`) — candidate for 1.1.

## Open questions
- Should `${VAR:-default}` be supported for non-secret values? (Proposed: yes for non-password fields.)

## Implementation notes (as built)
- `priority` is not defaulted (it depends on the server version); the AC5 text and 00-architecture.md were corrected to match CAP-005 AC3.
- An unresolved `${CAPELLA_ORG_ID}` in `organizationId` is not an error: the organization can come from a profile (CAP-037 precedence).
- Unquoted `on`/`off` in hibernation day keys are converted with a tip (CAP-020 AC10 behaviour, implemented early in the loader).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_validate_ac1_exit_code_3` (tests/scenario/test_validate.py)<br>`test_loader_ac1_error_has_path_and_line` (tests/unit/config/test_loader.py) |
| AC2 | `test_loader_ac2_env_reference_resolved` (tests/unit/config/test_secrets.py)<br>`test_loader_ac2_unset_env_names_variable` (tests/unit/config/test_secrets.py)<br>`test_loader_ac2_file_reference_resolved_relative_to_config` (tests/unit/config/test_secrets.py)<br>`test_loader_ac2_missing_file_names_path` (tests/unit/config/test_secrets.py)<br>`test_loader_ac2_errors_never_contain_value` (tests/unit/config/test_secrets.py) |
| AC3 | `test_loader_ac3_literal_password_rejected` (tests/unit/config/test_secrets.py) |
| AC4 | `test_crossref_ac4_unknown_bucket` (tests/unit/config/test_crossref.py)<br>`test_crossref_ac4_unknown_scope_and_collection` (tests/unit/config/test_crossref.py)<br>`test_crossref_ac4_external_bucket_allowed` (tests/unit/config/test_crossref.py)<br>`test_crossref_ac4_duplicate_names` (tests/unit/config/test_crossref.py)<br>`test_crossref_ac4_duplicate_cluster_names` (tests/unit/config/test_crossref.py)<br>`test_crossref_ac4_disk_type_matches_provider` (tests/unit/config/test_crossref.py)<br>`test_crossref_ac4_data_service_required` (tests/unit/config/test_crossref.py) |
| AC5 | `test_loader_ac5_bucket_defaults` (tests/unit/config/test_defaults.py)<br>`test_loader_ac5_cluster_defaults` (tests/unit/config/test_defaults.py) |
| AC6 | `test_validate_ac6_example_is_valid_offline` (tests/scenario/test_validate.py) |
| AC7 | `test_loader_ac7_unknown_api_version` (tests/unit/config/test_loader.py) |
