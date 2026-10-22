# CAP-036 — Import an existing project & clusters into capella.yaml

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P0 | 8 | CAP-005, CAP-020, CAP-022, CAP-025, CAP-027 | Implemented |

## User story
As an **operator whose clusters already exist in Capella**, I want `capellactl import` to read my project and clusters and write a `capella.yaml` that describes them exactly, so that I can start managing existing environments with the tool without retyping anything and without any change being made.

## Context & discovery
Everything the file declares can be read back from the API, with these known gaps:

| Resource | Read from | Gap / handling |
|---|---|---|
| Project | `GET …/projects/{id}` | — |
| Cluster | `GET …/clusters/{id}`: `name, description, configurationType, cloudProvider{type,region,cidr}, couchbaseServer.version, serviceGroups, availability, support, cmekId, enablePrivateDNSResolution, deletionProtection` | `zones` is **not** returned → omitted (omitted fields are not compared) |
| Hibernation | `GET …/onOffSchedule` (404 = none) | API form converted to the friendly form |
| Allowed CIDRs | `GET …/allowedcidrs`: `cidr, comment, expiresAt, status, type` | Entries with `status: expired` are skipped |
| Buckets | `GET …/buckets` | All create fields returned |
| Scopes / collections | `GET …/scopes` (+ collections, `maxTTL`) | `_default`, `_system` skipped unless they contain non-default collections |
| Database credentials | `GET …/users`: `name, access, userRoles` | **Passwords are never returned** → no `password:` written; existing passwords stay unchanged. Advanced credentials (`userRoles`, empty `access`) are written commented out with a note (1.0.0 manages basic only) |

List responses carry `cursor.pages` (`page`, `next`, `last`, `totalItems`); the client follows `next` (CAP-003).

## Implementation details

```
capellactl import --project nova-dev [--cluster nova-dev-01 …] [--file capella.yaml] [--full] [--stdout] [--force]
capellactl import --project-id 2b5c… --cluster-id 9f1e…
```

- `importer/` package: one `export(observed) -> dict` per reconciler kind (the inverse of `diff`), so import and plan share the same field mapping.
- **Minimal by default:** fields equal to the tool's defaults are omitted; `--full` writes every field.
- Writes a header comment with org, project, import time and tool version; each section has a short comment.
- Ambiguous names get an `id:` pin automatically.
- After writing, import runs `plan` internally and reports the result (AC2).

Example output (excerpt):
```yaml
# Imported by capellactl 1.0.0 on 2026-10-05T17:20:11Z from org 6af0…, project nova-dev
apiVersion: capellactl/v1
organizationId: 6af0…          # the organization the API Key Token was used with
project:
  name: nova-dev
clusters:
  - name: nova-dev-01
    deletionProtection: true
    cloudProvider: { type: aws, region: us-east-1, cidr: 10.10.0.0/23 }
    ...
    databaseCredentials:
      - name: orders_app
        # password not exported (Capella never returns it). Existing password is unchanged.
        # To rotate later: set password: ${ORDERS_APP_PASSWORD} and run credential update --rotate-password
        access:
          - privileges: [data_reader, data_writer]
            resources: { buckets: [ { name: orders } ] }
```

## Acceptance criteria & tests

### AC1 — Imports every managed resource kind
**Given** a fake project with one cluster that has a schedule, 2 CIDRs (one expired), 2 buckets with scopes/collections and 3 credentials (one advanced), **then** the file contains the project, cluster, schedule (friendly form), 1 CIDR, both buckets with their scopes/collections, 2 basic credentials, and the advanced credential commented out with a note.

| Test | Location | Verifies |
|---|---|---|
| `test_import_ac1_all_kinds_exported` | `tests/scenario/test_import.py` | Golden file |
| `test_import_ac1_expired_cidr_skipped` | same | |
| `test_import_ac1_advanced_credential_commented` | same | |
| `test_import_ac1_credential_without_access_listed_as_comment` | `tests/scenario/test_credential_access_kept.py` | No-access credential commented; file validates |

### AC2 — Round trip: plan after import shows no changes
**Given** any imported file, **when** `capellactl plan` runs against the same Capella state, **then** it prints `No changes` and `fake.writes() == []`. This holds for the minimal and `--full` outputs.

| Test | Location | Verifies |
|---|---|---|
| `test_import_ac2_round_trip_no_changes` | `tests/scenario/test_import.py` | Parametrised over 6 seeded fixtures × minimal/full |
| `test_import_ac2_round_trip_integration` | `tests/integration/test_import.py` | Real sandbox environment |

### AC3 — Import is read-only
**Given** any import, **then** only `GET` requests are sent.

| Test | Location | Verifies |
|---|---|---|
| `test_import_ac3_only_gets` | `tests/scenario/test_import.py` | |

### AC4 — No secrets in the file
**Given** credentials exist, **then** the file contains no `password:` values and no API key; each credential has the "password not exported" comment.

| Test | Location | Verifies |
|---|---|---|
| `test_import_ac4_no_secrets` | `tests/scenario/test_import.py` | |

### AC5 — Selecting what to import
**Given** `--cluster nova-dev-01`, **then** only that cluster is written. **Given** two clusters share a name, **then** both are written with `id:` pins and a warning; `--cluster-id` selects one.

| Test | Location | Verifies |
|---|---|---|
| `test_import_ac5_cluster_filter` | `tests/scenario/test_import.py` | |
| `test_import_ac5_ambiguous_names_pinned` | same | |

### AC6 — Minimal vs full
**Given** a bucket with all default values except memory, **then** minimal output has only `name` and `memoryAllocationInMb`; `--full` has every field.

| Test | Location | Verifies |
|---|---|---|
| `test_import_ac6_minimal_omits_defaults` | `tests/unit/importer/test_export_bucket.py` | |
| `test_import_ac6_full_has_all_fields` | same | |

### AC7 — Schedule converted to friendly form
**Given** an API schedule with Mon–Fri `custom 8:00–18:00` and Sat/Sun `off`, **then** the file has `weekdays: "08:00-18:00"` and `weekend: "off"` (quoted); otherwise `weekdays`/`weekend` take each group's most common value and the other days are written as per-day overrides (revised 2026-10-07 with CAP-020, so `sync` and `cluster schedule set` write the same form).

| Test | Location | Verifies |
|---|---|---|
| `test_import_ac7_schedule_compacted` | `tests/unit/importer/test_export_schedule.py` | |
| `test_import_ac7_schedule_irregular_per_day` | same | |

### AC8 — Output handling
**Given** the target file is an existing capella.yaml, **then** the missing projects are added and the others left alone (CAP-040). **Given** a file that is not a capellactl file, **then** import asks before overwriting (interactive), needs `--force` in scripts, and keeps a `.bak`. **Given** `--stdout`, **then** YAML goes to stdout only.

| Test | Location | Verifies |
|---|---|---|
| `test_import_ac8_existing_file_and_stdout` | `tests/scenario/test_import.py` | |

### AC9 — Turned-off clusters import fine
**Given** a `turnedOff` cluster, **then** cluster settings, schedule and allowed CIDRs are imported. Buckets and database credentials are not requested, because Capella rejects those calls while the cluster is off (500 for buckets, which would otherwise be retried six times, and 422 for credentials). They are marked `# not imported: buckets and database credentials (the cluster is turnedOff; …)` in the file, and import exits 0 with a warning. The same applies while the cluster is `turningOff` or `turningOn`. Other calls the API rejects are listed as `# not imported: …` in the same way.

| Test | Location | Verifies |
|---|---|---|
| `test_import_ac9_turned_off_cluster` | `tests/scenario/test_import.py` | |

## Out of scope
- Importing App Services, backups or other resources the tool does not manage (listed in a trailing comment as "present but not managed by capellactl 1.0.0").

## Open questions
- Can bucket/scope/credential lists be read while a cluster is `turnedOff`? (AC9 handles both outcomes; confirm which happens.)
- Does `couchbaseServer.version` come back as `7.6` or `7.6.2`? Import writes what is returned; confirm that a create-time short version compares equal (or ignore server version in comparison since it is immutable anyway).

## Implementation notes (as built)
- 2026-10-07: a basic credential with no access in Capella is listed as a commented entry with the command that gives it access (it cannot be written as a valid entry: `access` needs at least one grant). `sync` instead keeps the access the file already records and warns, so `apply` restores it. A list whose items are all commented out is written as `[]`, so the file still validates (this also fixed a cluster whose only credentials are advanced).
- Pulled forward from Phase 4 at the user's request: after `configure` saves the API Key Token it offers to discover the project and write `capella.yaml` (`--import/--no-import` for scripts), so nobody writes the file by hand. The README walkthrough no longer has a "create capella.yaml" step.
- `organizationId` is written as the literal organization ID (it is not secret); environment variables and profiles still take precedence.
- Project choice (revised by CAP-040): every project is imported by default; `--project` (repeatable) or `--project-id` limits it. An existing capella.yaml gets the missing projects appended; projects already in it are left alone (`sync` refreshes them); `--force` rewrites the whole file.
- A project without clusters gets `clusters: []` and a one-line note pointing to `capellactl cluster create NAME` (CAP-038); users never edit the file.
- Duplicate cluster names are counted across the whole project, so a filtered import still pins `id:`. Found by the round-trip test: the config check also rejected same-named clusters even when each was pinned; it now accepts them.
- AC2 is verified against six seeded environments (minimal, rich, single-node, two service groups, Azure, GCP enterprise) in minimal and `--full` mode, plus a run with child reconcilers. The real-sandbox variant (`test_import_ac2_round_trip_integration`) belongs to the nightly suite (CAP-032).
- Small leaf values (`compute`, `disk`, `services`, `privileges`, …) are written in one-line flow style to match the hand-written examples; comments are wrapped.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_import_ac1_all_kinds_exported` (tests/scenario/test_import.py)<br>`test_import_ac1_expired_cidr_skipped` (tests/scenario/test_import.py)<br>`test_import_ac1_advanced_credential_commented` (tests/scenario/test_import.py)<br>`test_import_ac1_credential_without_access_listed_as_comment` (tests/scenario/test_credential_access_kept.py) |
| AC2 | `test_import_ac2_round_trip_no_changes` (tests/scenario/test_import.py)<br>`test_import_ac2_round_trip_children_with_reconcilers` (tests/scenario/test_import.py) |
| AC3 | `test_import_ac3_only_gets` (tests/scenario/test_import.py) |
| AC4 | `test_import_ac4_no_secrets` (tests/scenario/test_import.py) |
| AC5 | `test_import_ac5_cluster_filter` (tests/scenario/test_import.py)<br>`test_import_ac5_ambiguous_names_pinned` (tests/scenario/test_import.py) |
| AC6 | `test_import_ac6_minimal_omits_defaults` (tests/scenario/test_import.py)<br>`test_import_ac6_full_has_all_fields` (tests/scenario/test_import.py) |
| AC7 | `test_import_ac7_schedule_compacted` (tests/scenario/test_import.py)<br>`test_import_ac7_schedule_irregular_per_day` (tests/scenario/test_import.py) |
| AC8 | `test_import_ac8_existing_file_and_stdout` (tests/scenario/test_import.py) |
| AC9 | `test_import_ac9_turned_off_cluster` (tests/scenario/test_import.py) |
