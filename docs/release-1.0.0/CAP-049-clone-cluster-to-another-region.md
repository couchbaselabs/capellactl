# CAP-049 — Clone a cluster into another region

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E3 Clusters | P1 | 5 | CAP-011, CAP-023, CAP-025, CAP-036, CAP-038, CAP-048 | Not started |

## User story
As a **platform engineer**, I want to pick an existing cluster from a project and deploy the same cluster in another region with one command, so that a second region (for disaster recovery, latency or a regional rollout) matches the first without retyping its size, services, buckets, scopes and collections, and without editing capella.yaml.

## Context & discovery
- Customer request: set up a cluster in one region, then deploy the same cluster in another region. Today this means reading the first cluster's settings with `cluster get` and `bucket list`, then running `cluster create`, `bucket create`, `scope create` and `collection create` again by hand. That is slow and easy to get wrong.
- `import` (CAP-036) already reads a cluster from Capella into the capella.yaml form: size, service groups, disks, support plan, availability, deletion protection, allowed CIDRs, buckets, scopes, collections, credentials and the hibernation schedule. Cloning reuses that reader, so nothing new is needed from the API.
- `cluster create` (CAP-038) already chooses a free network CIDR, validates the result, records it in capella.yaml, deploys it, pins its `id` (CAP-048) and restores the file when Capella rejects the create (CAP-038 AC8). Cloning goes through the same path.
- Some settings belong to a region and cannot be copied as they are: the cluster `cidr` (two clusters must not overlap, especially if they will later be connected with XDCR or peering), `zones` (availability-zone ids exist only in their own region) and the hibernation schedule's timezone (a choice the operator should make).
- A cluster name must be unique inside its project, so the clone needs a new name, or a different target project.
- Endpoints, all already used by `import` and the create commands:
  - read: `GET …/projects`, `GET …/projects/{projectId}/clusters`, `GET …/clusters/{clusterId}`, `GET …/buckets`, `GET …/scopes`, `GET …/allowedcidrs`, `GET …/users`
  - write: `POST …/projects/{projectId}/clusters`, `POST …/buckets`, `POST …/scopes`, `POST …/collections`, `POST …/allowedcidrs`, `POST …/users`, `PUT …/deletionProtection` (only for what is copied)

## Implementation details
- New command:
  ```
  capellactl cluster clone SOURCE NEW_NAME --region REGION
      [--project SOURCE_PROJECT] [--to-project TARGET_PROJECT]
      [--cidr CIDR] [--support-plan PLAN] [--description TEXT]
      [--with-cidrs] [--with-credentials] [--no-data-model]
      [--no-apply]
  ```
  - `SOURCE` is a cluster in Capella. `--project` picks its project when the cluster name is used in several projects, or when capella.yaml does not list it.
  - When a terminal is attached, the command asks for anything not given, in this order: source project (list of projects), source cluster (list of that project's clusters, showing provider, region and size), new name (default `SOURCE-<region>`), target region (default: none, it must be chosen), target project (default: the source project) and network CIDR (default: the first free `/24` that does not overlap any cluster in the target project or in the source cluster's project).
  - With `--auto-approve` and no terminal, `SOURCE`, `NEW_NAME` and `--region` are required; everything else uses the defaults above.
- What is copied from the source, read live from Capella and not from capella.yaml:
  - Copied as is: cloud provider, `configurationType`, every service group (compute, disk type, size and IOPS, number of nodes, services), `availability`, support plan and timezone, deletion protection, and the Couchbase Server version (see Open questions).
  - Copied unless `--no-data-model` is given: buckets with all their settings, scopes and collections (with `maxTTL`). Documents are **not** copied.
  - Copied only with `--with-cidrs`: allowed CIDRs. Their `expiresAt` is kept and their comments get `(cloned from SOURCE)`.
  - Copied only with `--with-credentials`: database credentials with the same names and access. Capella never returns passwords, so each clone credential gets a new generated password, saved like `credential create` saves one (CAP-046). A credential whose password is a `${VAR}` or `${file:…}` reference in capella.yaml keeps that reference.
- What is changed or dropped:
  - `name` = `NEW_NAME`, `region` = `--region`, `cidr` = `--cidr` or the free default, `description` = `--description` or `Clone of SOURCE (PROJECT, REGION)`.
  - `zones` are dropped (Capella chooses zones in the new region).
  - The hibernation schedule is not copied; the summary says so and shows the `cluster schedule` command (CAP-020) to add one.
  - `--support-plan` overrides the copied plan (for example `developer pro` for a cheaper standby).
- The clone is validated like any other cluster before anything is sent. This includes the region name check for its provider (`eastus` for azure, not `us-east-1`), CIDR overlap, disk type per provider and the single-node rules.
- Output before the confirmation: one line `Cloning SOURCE (PROJECT · azure eastus) → NEW_NAME (TARGET_PROJECT · azure westeurope)`, then the normal plan: `+ cluster`, then `+ bucket`, `+ scope`, `+ collection`, and with the options `+ allowed-cidr` and `+ credential`. After that come the lines for what was not copied (data, hibernation schedule, and CIDRs and credentials when their options were left out).
- Recording and deploying follow CAP-038:
  - The clone is added to the target project in capella.yaml, as if it had been created with `cluster create` and then `bucket`, `scope` and `collection create`.
  - It is deployed through `change_and_apply`, which waits for the cluster unless `--no-wait` is given. Children are created once the cluster is healthy, or deferred with `--no-wait` and created by the next `apply`.
  - If Capella rejects the cluster create, capella.yaml is restored (CAP-038 AC8). If an `id` is pinned after the create, it follows CAP-048.
- `-o json` prints the plan and the result in the same form as `apply`.
- Refused, with nothing written:
  - The source is a free-tier cluster: `free-tier clusters cannot be cloned (one per organization); use 'cluster create' instead`.
  - The source is not `healthy` or `turnedOff`: `cluster SOURCE is STATE; clone it once it is healthy`.
  - `NEW_NAME` already exists in the target project.
  - The target region equals the source region in the same project and no `--to-project` was given. This is allowed, but asks `Clone into the same region?` first, and needs `--auto-approve` without a terminal.

## Acceptance criteria & tests

### AC1 — Clone with flags
**Given** a healthy azure cluster `nova-demo-01` in `eastus` (project `nova-demo`) with 3 × 8 vCPU/32 GB, `data,index,query`, `P10` disks, support `enterprise`, and bucket `demo` with scope `inventory` and collections `airline` and `route`, **when** `capellactl --auto-approve cluster clone nova-demo-01 nova-demo-weu --region westeurope` runs, **then**:
- the plan shows `+ cluster nova-demo-weu  azure westeurope · multi-AZ · 3 × 8 vCPU/32 GB …`, `+ bucket nova-demo-weu/demo`, `+ scope nova-demo-weu/demo/inventory` and two `+ collection` lines;
- the `POST …/clusters` body equals the source's settings except `name`, `cloudProvider.region`, `cloudProvider.cidr` and `description`;
- capella.yaml has `nova-demo-weu` with its pinned `id` in project `nova-demo`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_clone_ac1_flags_copies_settings` | `tests/scenario/test_cluster_clone.py` | Plan, POST body, file |

### AC2 — Pick the source interactively
**Given** a terminal and no arguments, **then** `cluster clone` asks for the source project (from a list), the source cluster (from that project's clusters with provider, region and size), the new name (default `nova-demo-01-westeurope` once the region is chosen), the region, the target project (default the source project) and the CIDR (default the first free `/24`), then shows the plan and asks once.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_clone_ac2_interactive_picks_source` | `tests/scenario/test_cluster_clone.py` | |

### AC3 — Region-bound values are not copied
**Given** a source with `zones`, a hibernation schedule and CIDR `10.0.0.0/24`, **then** the clone has no `zones`, no `hibernation`, and a CIDR that overlaps neither the source nor any cluster in the target project (`10.0.1.0/24`). The output lists `not copied: documents, hibernation schedule`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_clone_ac3_region_bound_values_reset` | `tests/scenario/test_cluster_clone.py` | |

### AC4 — Optional parts
**Given** `--no-data-model`, **then** no bucket, scope or collection is planned. **Given** `--with-cidrs`, **then** the source's allowed CIDRs are planned with `(cloned from nova-demo-01)` in their comment. **Given** `--with-credentials`, **then** each credential is planned with the same access and a new generated password saved under `.capellactl/credentials/nova-demo-weu.NAME.json`, and no password appears in the output. Without the options, the output lists `not copied: allowed CIDRs, database credentials`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_clone_ac4_no_data_model` | `tests/scenario/test_cluster_clone.py` | |
| `test_cluster_clone_ac4_with_cidrs` | same | |
| `test_cluster_clone_ac4_with_credentials_new_passwords` | same | Redaction too |

### AC5 — Another project and overrides
**Given** `--to-project nova-dr --support-plan "developer pro" --cidr 10.20.0.0/24`, **then** the clone is recorded and created in `nova-dr` with plan `developer pro` and that CIDR. If `nova-dr` is not in capella.yaml but exists in Capella, it is added to the file first, like `import --project`. If it does not exist, the command stops and suggests `capellactl project create nova-dr`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_clone_ac5_to_project_with_overrides` | `tests/scenario/test_cluster_clone.py` | |
| `test_cluster_clone_ac5_missing_target_project` | same | |

### AC6 — Invalid clones write nothing
**Given** each of these, **then** the command exits with the stated code, capella.yaml is unchanged and nothing is sent:
- `--region us-east-1` for an azure source: exit 3, `us-east-1 is not an azure region name`;
- a `--cidr` that overlaps another cluster: exit 3;
- `NEW_NAME` already in the target project: exit 4;
- a free-tier source: exit 4, `free-tier clusters cannot be cloned`;
- a source in `deploying`: exit 4.

With a terminal, an invalid region or CIDR that was typed at a prompt is asked again, as in `cluster create`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_clone_ac6_invalid_input_writes_nothing` | `tests/scenario/test_cluster_clone.py` | Parametrized |

### AC7 — Rejected clone restores the file
**Given** Capella answers the cluster `POST` with `500` or `422`, **then** the error is shown, capella.yaml is restored, and running the same command again with corrected values succeeds (CAP-038 AC8).

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_clone_ac7_rejected_create_restores_file` | `tests/scenario/test_cluster_clone.py` | |

### AC8 — Idempotent
**Given** a finished clone, **then** `plan` reports no changes, a second `apply` makes zero `POST`/`PUT`/`DELETE` calls, and `sync --dry-run` reports the file in sync. Running the same `cluster clone` again exits 4 with `cluster nova-demo-weu already exists`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_clone_ac8_idempotent` | `tests/scenario/test_cluster_clone.py` | |

### AC9 — Real sandbox
**Given** the sandbox organization, **then** a single-node source in one region is cloned to another region with one bucket, scope and collection, reaches `healthy`, and is deleted by the test.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_clone_ac9_integration` | `tests/integration/test_cluster_clone.py` | Nightly (CAP-032) |

## Out of scope
- Copying documents, or keeping the two clusters in sync. That needs XDCR replication or a backup and restore, which are not part of 1.0.0. The summary points to them.
- Cloning to another cloud provider. Disk types, sizes and the free-tier rules differ, so the provider is always copied. Proposed for later as `--provider` with a disk mapping.
- Cloning several clusters, or a whole project, at once.
- App Services and other linked services (release 2.0.0).

## Open questions
- Server version: should the clone request the source's exact Couchbase Server version, or leave it out so Capella picks the current default? Proposed: request the source's version, and if Capella rejects it (no longer offered in that region), stop and suggest `--server-version latest`.
- Should the clone be recorded with a link to its source (for example a `clonedFrom:` comment in capella.yaml), so a later `cluster clone --refresh` can copy new buckets and collections across? Proposed: a YAML comment only in 1.0.0.
- Deletion protection: copy the source's setting (proposed), or always leave it off on a new standby?
