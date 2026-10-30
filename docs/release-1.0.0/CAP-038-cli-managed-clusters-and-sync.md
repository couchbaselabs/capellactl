# CAP-038 — Manage clusters from the CLI: deploy, change and sync without editing capella.yaml

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E3 Clusters | P0 | 8 | CAP-011, CAP-012, CAP-015, CAP-036 | Implemented |

## User story
As an **operator**, I want to deploy a new cluster, change an existing one, and refresh `capella.yaml` from Capella using `capellactl` commands only, with the tool asking me for anything it needs, so that I never have to edit YAML by hand.

## Context & discovery
- Product decision (2026-10-05): **`capella.yaml` is owned by the tool.** Users are never asked to edit it. Every change goes through a command that validates the input, updates the file, shows the plan, asks once, and applies. The file remains the reviewable record of the environment (and what `plan`/`apply` compare against).
- After CAP-036 the file is created by discovery; this story adds the commands that change it.
- Edits must keep the comments that import writes (password notes, advanced-credential blocks), so the file is edited with a round-trip YAML library (`ruamel.yaml`), not re-rendered.
- Cluster create rules come from the OpenAPI spec (CAP-011): provider `aws|gcp|azure`, disk types per provider, node limits, `singleNode` with `availability: single` (any provider).
- Supported compute sizes per region are not in the spec (CAP-011 open question). Presets are therefore conservative and the API's `422` is shown if a size is not offered in that region.

## Implementation details

### Commands

| Command | What it does |
|---|---|
| `capellactl cluster create NAME [options]` | Asks for missing details (or takes flags), adds the cluster to capella.yaml, shows the plan, asks once, deploys and waits until healthy |
| `capellactl cluster update NAME [options]` | Changes description, support plan/timezone, CPU/RAM, disk; same flow |
| `capellactl cluster scale NAME --nodes N [--group]` | Now also records the new node count in capella.yaml, so file and Capella always agree |
| `capellactl sync [--cluster NAME] [--dry-run] [--full]` | Refreshes capella.yaml from Capella for the project in the file; shows a diff; keeps a `.bak` |

Shared flags: `--no-apply` (write the file only), global `--auto-approve`, `--no-wait`.

`cluster create` options: `--provider aws|gcp|azure`, `--region`, `--cidr`, `--size dev|small|medium|large`, `--nodes`, `--cpu`, `--ram`, `--disk-type`, `--disk-size`, `--disk-iops`, `--services`, `--availability single|multi`, `--support-plan`, `--support-timezone`, `--description`.

### Defaults

| Item | Default |
|---|---|
| Region | aws `us-east-1`, gcp `us-east1`, azure `eastus` |
| CIDR | first free `10.x.y.0/24` (in address order) that overlaps no cluster in the file or in Capella |
| Size presets | `dev`: 1 × 4 vCPU/16 GB, singleNode (any provider) · `small`: 3 × 4/16 · `medium`: 3 × 8/32 · `large`: 5 × 16/64 |
| Disk | aws `gp3` 50 GB 3000 IOPS · gcp `pd-ssd` 50 GB · azure `P6` |
| Services | `data, index, query` |
| Availability | `multi` (`single` for `dev`) |
| Support | `developer pro`, timezone `PT` |

### Sync keeps what Capella cannot return
Password references (`password: ${VAR}`), `credentialsOutput`, `allowAnyIp`, and an `organizationId` written as `${VAR}` are carried over from the current file.

## Acceptance criteria & tests

### AC1 — Deploy a new cluster interactively
**Given** capella.yaml with a project, **when** the operator runs `capellactl cluster create nova-dev-02` and answers the prompts (pressing Enter accepts each default), **then** the tool shows a summary and the plan (`+ cluster nova-dev-02 …`), asks `Add nova-dev-02 to capella.yaml and deploy it now?`, and on yes writes the cluster into capella.yaml, sends one `POST …/clusters`, waits until healthy and prints the connection string.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_create_ac1_interactive_deploys` | `tests/scenario/test_cluster_cli.py` | Prompts, file content, one POST, healthy |

### AC2 — Non-interactive create
**Given** no terminal, **when** `capellactl --auto-approve cluster create NAME --provider gcp --size medium` runs, **then** the cluster is written and deployed using flags plus defaults. **Given** no terminal and no `--auto-approve`, **then** exit 1 and nothing is written.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_create_ac2_flags_and_defaults` | `tests/scenario/test_cluster_cli.py` | |
| `test_cluster_create_ac2_non_interactive_needs_auto_approve` | same | |

### AC3 — Defaults and a free CIDR
**Given** clusters using `10.10.0.0/23` (in the file) and `10.0.0.0/23` (only in Capella), **then** the suggested CIDR is the first free `/24` overlapping neither; region and disk defaults follow the provider; presets set nodes, CPU and RAM.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_defaults_ac3_free_cidr` | `tests/unit/cli/test_cluster_defaults.py` | |
| `test_cluster_defaults_ac3_provider_and_presets` | same | |

### AC4 — Validated before anything is written
**Given** an invalid answer or flag (for example `--provider gcp --disk-type gp3`, `--nodes 2` on a multiNode cluster, `--size dev --provider azure`), **then** the same message as `capellactl validate` is shown, interactive prompts ask again, non-interactive runs exit 3, and capella.yaml is unchanged.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_create_ac4_invalid_input_writes_nothing` | `tests/scenario/test_cluster_cli.py` | Parametrised |

### AC5 — Name already used
**Given** a cluster with that name in capella.yaml or in the project in Capella, **then** `cluster create` exits 4 with `cluster NAME already exists; use 'capellactl cluster update' or 'capellactl cluster scale', or 'capellactl sync' to bring it into capella.yaml`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_create_ac5_existing_name` | `tests/scenario/test_cluster_cli.py` | File and Capella cases |

### AC6 — Scale records the change in capella.yaml
**Given** `capellactl cluster scale nova-dev-01 --nodes 5`, **then** capella.yaml is updated to 5 nodes for that group and the cluster is scaled; a later `plan` reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_scale_ac6_updates_file` | `tests/scenario/test_cluster_cli.py` | |

### AC7 — Update settings from the CLI
**Given** `capellactl cluster update nova-dev-01 --support-plan enterprise --description "…" --cpu 8 --ram 32`, **then** the file is updated, the plan shows the field changes, and one `PUT` is sent after confirmation. Immutable fields (provider, region, CIDR, availability) are not offered as options.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_update_ac7_changes_file_and_applies` | `tests/scenario/test_cluster_cli.py` | |
| `test_cluster_update_ac7_no_immutable_options` | same | |
| `test_cluster_update_ac7_azure_premium_disk_not_resized` | same | Azure P6: no disk size/IOPS sent; `--disk-size` refused |

### AC8 — Safe file handling
**Given** the operator declines the confirmation, **then** capella.yaml is unchanged. **Given** `--no-apply`, **then** the file is written (with a `.bak` copy) and nothing is sent to Capella. Comments already in the file are kept. **Given** Capella rejects the change before accepting any write (for example a `500` or `422` on the create), **then** capella.yaml is restored to its previous content and the error says so, instead of "re-run apply"; this holds for every command that writes the file before deploying (cluster, bucket, scope, credential, allowed CIDR). When a write may have landed (accepted, lost connection, interrupted) the file is kept. **Given** a cluster that is in capella.yaml but was never deployed (no `id`, not in Capella), **then** `cluster create NAME` with new values replaces it, keeping its buckets and other settings, so the user never edits the file; a cluster that was deployed once (has an `id`) is still refused.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_cli_ac8_decline_writes_nothing` | `tests/scenario/test_cluster_cli.py` | |
| `test_cluster_cli_ac8_no_apply_and_comments_kept` | same | |
| `test_cluster_cli_ac8_rejected_create_restores_file` | same | Capella `500` on create |
| `test_cluster_cli_ac8_accepted_create_keeps_file` | same | Failure after the create was accepted |
| `test_cluster_cli_ac8_rerun_replaces_undeployed_entry` | same | |
| `test_cluster_cli_ac8_deployed_entry_still_blocked` | same | |
| `test_cluster_cli_ac8_new_keys_in_import_order` | same | New keys placed as import writes them |
| `test_bucket_cli_ac8_rejected_create_restores_file` | `tests/scenario/test_bucket.py` | Same rule for other commands |

### AC9 — Sync capella.yaml from Capella
**Given** a cluster changed or added outside capellactl, **when** `capellactl sync` runs, **then** capella.yaml is rewritten from Capella for the project in the file, a diff of the change is shown, the previous file is kept as `.bak`, and password references, `credentialsOutput`, `allowAnyIp` and an `${…}` organizationId are kept. A second `sync` prints `capella.yaml is already in sync with Capella`.

| Test | Location | Verifies |
|---|---|---|
| `test_sync_ac9_refreshes_with_diff` | `tests/scenario/test_sync.py` | |
| `test_sync_ac9_keeps_local_only_values` | same | |
| `test_sync_ac9_second_run_in_sync` | same | |
| `test_sync_ac9_whole_bucket_wildcard_not_written` | same | Capella's `*` scope not written |
| `test_sync_ac9_file_with_wildcard_still_loads` | same | |
| `test_sync_ac9_keeps_access_capella_lost` | `tests/scenario/test_credential_access_kept.py` | Access kept from the file, warning shown |

### AC10 — Sync dry run for CI
**Given** `capellactl sync --dry-run`, **then** the diff is shown and nothing is written; exit 2 when the file is out of sync, 0 when in sync.

| Test | Location | Verifies |
|---|---|---|
| `test_sync_ac10_dry_run_exit_codes` | `tests/scenario/test_sync.py` | |

### AC11 — Read-only and idempotent
**Given** `sync`, **then** only `GET` requests are sent. **Given** a cluster just created with `cluster create`, **then** `apply` and `sync --dry-run` both report no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_cli_ac11_create_then_in_sync` | `tests/scenario/test_cluster_cli.py` | |
| `test_sync_ac11_only_gets` | `tests/scenario/test_sync.py` | |

### AC12 — README never asks the user to edit capella.yaml
**Given** the README step-by-step, **then** every step is a `capellactl` command; no step tells the operator to edit capella.yaml. The walkthrough test runs those steps.

| Test | Location | Verifies |
|---|---|---|
| `test_readme_ac12_no_manual_edit_steps` | `tests/scenario/test_readme_walkthrough.py` | Text check |
| `test_readme_walkthrough_steps` | same | Runs the steps |

### AC13 — Sync removes what was deleted in Capella, with everything under it
Parent → child: when a parent is deleted in Capella, its children are deleted too (project → clusters → buckets, scopes, collections, credentials, allowed CIDRs, schedules), so sync removes the parent and its whole subtree from capella.yaml.

**Given** a project in capella.yaml that was deployed once (it or one of its clusters has an `id`) and no longer exists in Capella, **when** `capellactl sync` runs, **then** it is removed from capella.yaml with all its clusters, the diff shows the removal and a warning names it; the user never removes it by hand. When the last project is removed, the file keeps `projects: []` with a pointer to `capellactl project create` and still validates. **Given** a cluster with an `id` that no longer exists in Capella, **then** `sync` and `sync --cluster NAME` remove it with its buckets, credentials and other settings (before, `--cluster` failed with "not found"). A project that was never deployed (no `id` anywhere) is kept with a warning to deploy it with `capellactl apply`.

| Test | Location | Verifies |
|---|---|---|
| `test_sync_ac13_removes_project_deleted_in_capella` | `tests/scenario/test_sync.py` | Other projects kept; second sync in sync |
| `test_sync_ac13_last_project_deleted_leaves_valid_file` | same | |
| `test_sync_ac13_keeps_project_never_deployed` | same | |
| `test_sync_ac13_removes_cluster_deleted_in_capella` | same | With and without `--cluster` |

### AC14 — Sync never drops what Capella cannot return right now
Capella does not answer bucket and credential reads while a cluster is `turnedOff`, `turningOff` or `turningOn`, and any read can fail. Sync must not mistake "not readable now" for "deleted": the file would lose buckets and credentials that still exist, a `password: ${VAR}` reference would be lost for good, and `apply --prune` after the cluster is back on would delete those buckets and credentials in Capella.

**Given** a cluster recorded with buckets and credentials (one with `password: ${APP_PASSWORD}`), **when** it is turned off and `capellactl sync` runs, **then** its buckets, scopes, collections and credentials are kept exactly as they were, the file notes `kept from the previous capella.yaml … (not readable now: turnedOff; the next sync refreshes them)`, the output says `kept from capella.yaml (turnedOff)` instead of `not imported`, and `sync --dry-run` exits 0. **When** it is on again, `apply --prune` deletes nothing and the next sync refreshes it with the password reference kept. **Given** a read of allowed CIDRs, buckets, a bucket's scopes, credentials or the schedule that fails with an API error, **then** the same applies to that part only. **Given** a cluster that was never recorded with that part (first sync while it is off), **then** the `not imported` note and warning stay.

| Test | Location | Verifies |
|---|---|---|
| `test_sync_ac14_turned_off_cluster_keeps_buckets_and_credentials` | `tests/scenario/test_sync.py` | Kept, dry run 0, prune deletes nothing, password kept |
| `test_sync_ac14_read_error_keeps_previous_values` | same | `GET …/users` 500 |
| `test_sync_ac14_first_sync_of_turned_off_cluster_still_notes_it` | same | |

### AC15 — A cluster network never overlaps one that is already in Capella
`cluster create` checks the network (`--cidr`, the answer, or the default) before anything is written or sent. The
file's validation already refuses an overlap with a cluster the file lists; this AC adds clusters that exist in
Capella but not in capella.yaml (created in the UI since the last `sync`), and other projects.

**Given** a cluster `ui-made` on `10.0.0.0/24` in the same project in Capella but not in capella.yaml, **when**
`cluster create test-01 --cidr 10.0.0.0/24` runs (with or without `--no-apply`), **then** it exits 3 with
`[ERROR]: 10.0.0.0/24 overlaps the network of cluster ui-made (10.0.0.0/24), which is in this project in Capella but
not in capella.yaml` and an `[ACTION]` naming a free range, makes no write, and leaves the file unchanged; the free
tier is refused the same way. **When** the overlapping range was typed at the question, **then** the error is shown
and only that question is asked again. **Given** an overlapping cluster in another project, **then** a `[WARNING]`
names it and the create goes on.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_create_ac15_overlap_with_capella_only_cluster_refused` | `tests/scenario/test_cluster_cli.py` | Flag, `--no-apply`, free tier; zero writes |
| `test_cluster_create_ac15_overlap_typed_is_reasked` | same | |
| `test_cluster_create_ac15_other_project_warns` | same | |

## Out of scope
- Commands for buckets, scopes, collections, credentials, IP allowlist and schedules (they arrive with CAP-022 to CAP-028, following the same pattern).
- Deleting clusters (CAP-014).

## Open questions
- Are the `medium`/`large` preset sizes offered in every region the customer uses? Presets live in one table so they are easy to adjust.
- Azure default disk `P6`: confirm it is acceptable for the customer's smallest clusters.

## Implementation notes (as built)
- Default CIDR changed from `/23` to `/24` (2026-10-07): Capella's API and docs set no size rule (the spec's `10.1.30.0/23` is only an example), and multi-AZ production clusters run on `/24` networks. The suggestion walks `10.0.0.0/24`, `10.0.1.0/24`, … and returns the first that overlaps no cluster; any size the user types is still accepted.
- Every command follows one path (`capellactl/cli/cluster_ops.py::change_and_apply`): change the file in memory → validate it exactly like `capellactl validate` (a temporary candidate file next to capella.yaml) → plan → ask once → write capella.yaml with a `.bak` → apply. Blocked, invalid or declined changes write nothing.
- capella.yaml is edited with `ruamel.yaml` round-trip mode (`capellactl/config/editor.py`), so comments written by import and the one-line style survive. New entries use the same compact style as import.
- After a successful `cluster create`, the Couchbase Server version Capella chose is recorded in the file, so `sync` has nothing to add (AC11).
- `cluster scale` now records the node count in capella.yaml; CAP-015 AC6 (drift note) was revised accordingly.
- Validation gained two rules found while building this: a cluster `cidr` must be a network address, and cluster networks in the file must not overlap.
- `sync` compares data, not text, so comments and formatting never count as changes; its diff shows only real differences. `sync --cluster NAME` refreshes one cluster and leaves the others as they are.
- Sync used to keep a project that was deleted in Capella ("kept as it is in capella.yaml"), leaving the user to remove it by hand; added AC13 (2026-10-07) so sync removes it. Deleted clusters were already dropped, since a project's clusters are rebuilt from Capella.
- The step-by-step walkthrough moved from README.md to `docs/getting-started.md` (2026-10-07) to keep the README short; AC12's tests now read the guide, and the README's quick start uses only `capellactl` commands too.
- Capella returns a whole-bucket credential grant as `scopes: [{name: '*'}]` (`*` = every scope/collection). Sync used to write that into capella.yaml, after which every command failed with `scope '*' is not defined in bucket` (found 2026-10-07). `resources/credential.py::without_wildcards` now drops `*` levels when the file is written and when access is compared, validation tolerates `*` in older files, and the fake Capella returns the wildcard like Capella does.
- Azure premium disks (P6 … P60) have a size and IOPS set by their type. Capella returns `storage`/`iops` for them on `GET` but refuses them in a request (`422 Cannot specify disk size or IOPS for disk type P6`), so every `cluster update` of an Azure cluster failed (found 2026-10-07). Create and update bodies now drop them for every Azure type except Ultra (`resources/cluster.py::fixed_size_disk`), `cluster update --disk-size/--disk-iops` is refused for those disks, and the fake Capella behaves the same way.
- A key a command adds (for example `description` from `cluster update`, `deletionProtection` from `cluster protect`) used to be appended after the cluster's buckets and credentials, where users did not find it (2026-10-07). `config/editor.py::put` now inserts new keys in import's order (`CLUSTER_KEY_ORDER`), and sync keeps a carried-over `password:` right after the credential's name.
- On an invalid interactive answer, the question round repeats with the previous good answers as defaults, but not the answer that caused the error.
- Found 2026-10-23: sync rebuilt a turned-off cluster without its buckets and credentials, so they disappeared from capella.yaml (and `apply --prune` would then have deleted them once the cluster was on). Added AC14: the importer now records which parts of each cluster it could not read (`ImportResult.unread`), and `cli/sync.py::_keep_unread` keeps those parts from the previous file.
- The empty-project template that told users to uncomment YAML was replaced by a pointer to `capellactl cluster create`; help topics and the README no longer ask anyone to edit the file.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_cluster_create_ac1_interactive_deploys` (tests/scenario/test_cluster_cli.py) |
| AC2 | `test_cluster_create_ac2_flags_and_defaults` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_create_ac2_non_interactive_needs_auto_approve` (tests/scenario/test_cluster_cli.py) |
| AC3 | `test_cluster_defaults_ac3_free_cidr` (tests/unit/cli/test_cluster_defaults.py)<br>`test_cluster_defaults_ac3_provider_and_presets` (tests/unit/cli/test_cluster_defaults.py) |
| AC4 | `test_cluster_create_ac4_invalid_input_writes_nothing` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_create_ac4_interactive_reasks` (tests/scenario/test_cluster_cli.py) |
| AC5 | `test_cluster_create_ac5_existing_name` (tests/scenario/test_cluster_cli.py) |
| AC6 | `test_cluster_scale_ac6_updates_file` (tests/scenario/test_cluster_cli.py) |
| AC7 | `test_cluster_update_ac7_changes_file_and_applies` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_update_ac7_no_immutable_options` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_update_ac7_interactive_asks` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_update_ac7_azure_premium_disk_not_resized` (tests/scenario/test_cluster_cli.py) |
| AC8 | `test_cluster_cli_ac8_decline_writes_nothing` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_cli_ac8_no_apply_and_comments_kept` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_cli_blocked_change_writes_nothing` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_cli_ac8_rejected_create_restores_file` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_cli_ac8_accepted_create_keeps_file` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_cli_ac8_rerun_replaces_undeployed_entry` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_cli_ac8_deployed_entry_still_blocked` (tests/scenario/test_cluster_cli.py)<br>`test_cluster_cli_ac8_new_keys_in_import_order` (tests/scenario/test_cluster_cli.py)<br>`test_bucket_cli_ac8_rejected_create_restores_file` (tests/scenario/test_bucket.py) |
| AC9 | `test_sync_ac9_refreshes_with_diff` (tests/scenario/test_sync.py)<br>`test_sync_ac9_keeps_local_only_values` (tests/scenario/test_sync.py)<br>`test_sync_ac9_second_run_in_sync` (tests/scenario/test_sync.py)<br>`test_sync_ac9_whole_bucket_wildcard_not_written` (tests/scenario/test_sync.py)<br>`test_sync_ac9_file_with_wildcard_still_loads` (tests/scenario/test_sync.py)<br>`test_sync_ac9_keeps_access_capella_lost` (tests/scenario/test_credential_access_kept.py) |
| AC10 | `test_sync_ac10_dry_run_exit_codes` (tests/scenario/test_sync.py) |
| AC11 | `test_cluster_cli_ac11_create_then_in_sync` (tests/scenario/test_cluster_cli.py)<br>`test_sync_ac11_only_gets` (tests/scenario/test_sync.py) |
| AC12 | `test_readme_ac12_no_manual_edit_steps` (tests/scenario/test_readme_walkthrough.py)<br>`test_readme_walkthrough_steps` (tests/scenario/test_readme_walkthrough.py) |
| AC13 | `test_sync_ac13_removes_project_deleted_in_capella` (tests/scenario/test_sync.py)<br>`test_sync_ac13_last_project_deleted_leaves_valid_file` (tests/scenario/test_sync.py)<br>`test_sync_ac13_keeps_project_never_deployed` (tests/scenario/test_sync.py)<br>`test_sync_ac13_removes_cluster_deleted_in_capella` (tests/scenario/test_sync.py) |
| AC14 | `test_sync_ac14_turned_off_cluster_keeps_buckets_and_credentials` (tests/scenario/test_sync.py)<br>`test_sync_ac14_read_error_keeps_previous_values` (tests/scenario/test_sync.py)<br>`test_sync_ac14_first_sync_of_turned_off_cluster_still_notes_it` (tests/scenario/test_sync.py) |
- **AC15** (2026-10-30, customer question): a `--cidr` was checked only against the clusters in capella.yaml, so one
  that overlapped a cluster created in the Capella UI since the last `sync` was sent to Capella. `cluster create`
  already read the project's clusters (for the suggested range); `ask_cidr` now also refuses an overlap with those
  that the file does not list, and `warn_other_projects` warns about other projects (one `list_clusters` call per
  project, only when the command gets that far).
