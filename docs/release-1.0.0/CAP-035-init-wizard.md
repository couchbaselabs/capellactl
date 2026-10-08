# CAP-035 — `init` wizard: create capella.yaml interactively

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E2 Projects | P0 | 5 | CAP-002, CAP-003, CAP-009 | Implemented |

## User story
As an **operator setting up Capella for the first time**, I want `capellactl init` to ask me a few questions and write a valid, commented `capella.yaml`, so that I can describe my project and cluster without learning the file format first.

## Context & discovery
- The file format is CAP-002; this story produces it rather than requiring it to be written by hand.
- With an API key available (`CAPELLA_API_KEY`, or a saved profile once CAP-037 ships), `init` can offer real choices: `GET /v4/organizations` (organizations), `GET …/projects` (existing projects).
- Starting from an existing cluster is CAP-036; `init` hands over to it when the user chooses that path, so there is one entry point.
- Presets keep the first experience short; their sizes live in `capellactl/config/presets.yaml` so they can be changed without code changes.

## Implementation details

### Flow
```
$ capellactl init
? Start from                      › New environment / Existing Capella project (import)
? Organization                    › Nova Corp (6af0…)        [from API; or typed ID if no key]
? Project                         › nova-dev (new)  | existing projects…
? Cluster name                    › nova-dev-01
? Cloud provider                  › aws | gcp | azure
? Region                          › us-east-1
? Size preset                     › dev (single node) | small (3 nodes) | custom
? Support plan                    › developer pro
? Protect from deletion?          › yes
? Hibernate outside office hours? › no | weekdays 08:00–18:00 (timezone US/Pacific)
? Allowed IP ranges (CIDR)        › 203.0.113.10/32, …
? Add a bucket now?               › orders · 1024 MB · magma → scope/collection names
? Add an app credential?          › orders_app · read+write on orders · password env var ORDERS_APP_PASSWORD
✔ Wrote capella.yaml (validated)
Next: export ORDERS_APP_PASSWORD=…   then   capellactl plan
```

### Behaviour
- Output path: `--file` (default `capella.yaml`; `.yml` accepted).
- Writes comments explaining each section and links to `capellactl help config <field>`.
- Never writes the API key or any password; credentials get `password: ${<ENV_NAME>}`.
- Runs CAP-002 validation before writing; invalid answers are re-asked, not written.
- Non-interactive mode for scripts:
  `capellactl init --non-interactive --org-id … --project nova-dev --cluster nova-dev-01 --provider aws --region us-east-1 --preset small [--hibernation office-hours --timezone US/Pacific] [--cidr …]`
- `--dry-run` prints the YAML to stdout instead of writing.

## Acceptance criteria & tests

### AC1 — Interactive happy path writes a valid file
**Given** scripted answers for the flow above, **then** `capella.yaml` is written, passes `capellactl validate`, contains the chosen values, and the command prints the next steps.

| Test | Location | Verifies |
|---|---|---|
| `test_init_ac1_interactive_writes_valid_file` | `tests/scenario/test_init.py` | Answers fed via `CliRunner(input=…)`; golden file |

### AC2 — Uses live choices when an API key is available
**Given** an API key, **then** organizations come from `GET /v4/organizations` and projects from `GET …/projects`; choosing an existing project writes its name and `id:` pin only when the name is ambiguous. **Given** no key, **then** the org ID is typed and a hint to run `capellactl configure` is shown. In both cases `init` makes **no** write calls to Capella.

| Test | Location | Verifies |
|---|---|---|
| `test_init_ac2_lists_orgs_and_projects` | `tests/scenario/test_init.py` | |
| `test_init_ac2_without_key_typed_org` | same | |
| `test_init_ac2_never_writes_to_capella` | same | `fake.writes() == []` |

### AC3 — Presets
**Given** preset `dev`, **then** the cluster is `singleNode` on any provider, 1 node, `availability: single`; **given** `small`, **then** `multiNode`, 3 nodes, `data,index,query`; values come from `presets.yaml`.

| Test | Location | Verifies |
|---|---|---|
| `test_init_ac3_presets_from_file` | `tests/unit/cli/test_init_presets.py` | |
| `test_init_ac3_dev_preset_requires_aws` | same | |

### AC4 — Secrets never written
**Given** a credential is added, **then** the file contains `password: ${ORDERS_APP_PASSWORD}` and no literal password; the API key never appears in the file.

| Test | Location | Verifies |
|---|---|---|
| `test_init_ac4_no_secrets_in_file` | `tests/scenario/test_init.py` | `assert_no_secret` on file content |

### AC5 — Never overwrite silently
**Given** `capella.yaml` exists, **then** `init` asks `capella.yaml exists. Overwrite? [y/N]` (default no); in non-interactive mode it exits 1 unless `--force`. A backup `capella.yaml.bak` is written before overwriting.

| Test | Location | Verifies |
|---|---|---|
| `test_init_ac5_existing_file_prompt` | `tests/scenario/test_init.py` | |
| `test_init_ac5_non_interactive_requires_force` | same | |
| `test_init_ac5_backup_written` | same | |

### AC6 — Invalid answers re-asked
**Given** an invalid cluster name, a CIDR with host bits, or a schedule minute of `15`, **then** the wizard shows the CAP-002 validation message and asks again.

| Test | Location | Verifies |
|---|---|---|
| `test_init_ac6_invalid_answers_reprompted` | `tests/scenario/test_init.py` | Parametrised |

### AC7 — Non-interactive and dry run
**Given** the non-interactive flags above, **then** the same file as AC1 (for the same choices) is produced without prompts; **given** `--dry-run`, **then** YAML goes to stdout and no file is written. Missing required flags exit 3 naming them.

| Test | Location | Verifies |
|---|---|---|
| `test_init_ac7_non_interactive_matches_interactive` | `tests/scenario/test_init.py` | |
| `test_init_ac7_dry_run_stdout_only` | same | |
| `test_init_ac7_missing_flags` | same | |

### AC8 — Import path
**Given** the answer `Existing Capella project (import)`, **then** the wizard asks for the project (and optionally clusters) and runs CAP-036 with the same output file.

| Test | Location | Verifies |
|---|---|---|
| `test_init_ac8_delegates_to_import` | `tests/scenario/test_init.py` | |

### AC9 — Plan after init
**Given** AC1's file against an empty organization, **then** `capellactl plan` shows only `+` actions for the declared resources and no errors.

| Test | Location | Verifies |
|---|---|---|
| `test_init_ac9_plan_after_init` | `tests/scenario/test_init.py` | |

## Out of scope
- Editing an existing file through the wizard (use the editor; `help config` explains fields).

## Open questions
- Confirm the preset compute sizes (`dev`, `small`) are offered in the customer's regions; adjust `presets.yaml` accordingly.

## Implementation notes (as built)

- `capellactl init` lives in `cli/init.py` (replacing the stub). Every answer updates an in-memory document, which is rendered and run through the real `load_config` (CAP-002 schema + cross-reference rules) after each answer. An issue on the field just asked is shown as `PATH: message`, followed by `Please answer again.` (AC6). The file is written only when the whole document validates. Password variables get a placeholder value during this validation, so `validate` passes without the secret being set.
- **Flow as built**: Start from (new/import) → organization (listed from `GET /v4/organizations` and chosen automatically when there is one) → project (numbered list of existing projects, or a new name) → cluster name (default `PROJECT-01`; a name already used in an existing project is re-asked) → provider → region → **cluster network CIDR** (not in the original flow; defaults to the first free `10.x.y.0/24` that overlaps none of the project's clusters) → size preset → support plan → deletion protection → office-hours hibernation (weekday window and timezone; weekend off) → allowed IP ranges (`0.0.0.0/0` asks for confirmation and sets `allowAnyIp`) → bucket (name, memory, storage backend, `scope:coll1,coll2;scope2`) → app credential (only offered with a bucket; read or read-write; password variable `NAME_PASSWORD`).
- **AC2**: an existing project is written by name, with `id:` only when several projects share the name. The file records `organizationId` literally, not `${CAPELLA_ORG_ID}`.
- **AC3**: presets live in `capellactl/config/presets.yaml` (`dev`, `small`, `medium`, `large`; loader `config/presets.py`, packaged in the wheel). `capellactl cluster create` now reads the same file, so the two commands cannot drift apart. `dev` works on AWS, GCP and Azure (the Capella UI deploys single-node clusters on all three; the earlier AWS-only rule was removed).
- **AC6**: two validation rules were added to CAP-002 for this: readable length messages (`must be at most 256 characters`) with `minLength: 1` on cluster names, and on-window checks (`minute must be 00 or 30`, hour range, start before end) ahead of CAP-020, which owns the rest of the schedule validation.
- **AC7**: `--non-interactive` (also used automatically without a terminal) takes `--org-id` (or the profile / `CAPELLA_ORG_ID`), `--project`, `--project-id`, `--cluster`, `--provider`, `--region`, `--network-cidr`, `--preset`, `--nodes/--cpu/--ram`, `--support-plan`, `--protect/--no-protect`, `--hibernation office-hours`, `--office-hours`, `--timezone`, `--cidr`…, `--allow-any-ip`, `--bucket`, `--bucket-memory`, `--storage-backend`, `--scope`…, `--credential`, `--access`, `--password-env`. The file has no timestamp, so the same choices give a byte-identical file.
- **AC8**: the import path asks for the project (numbered list) and optional cluster names, then runs `run_import` with `force=True` on the same file (the overwrite question has already been asked). It needs an API key.
- **AC9**: the plan after `init` has only `+` lines for what this build manages; scopes/collections (CAP-025), credentials (CAP-027) and the hibernation schedule (CAP-020) show as `…` deferred until those stories ship.
- Tests (`tests/scenario/test_init.py` unless noted; golden file `tests/scenario/fixtures/init_capella.yaml`): AC1 `test_init_ac1_interactive_writes_valid_file`; AC2 `test_init_ac2_lists_orgs_and_projects`, `test_init_ac2_without_key_typed_org`, `test_init_ac2_never_writes_to_capella`, `test_init_ac2_existing_cluster_name_reasked`; AC3 `tests/unit/cli/test_init_presets.py::test_init_ac3_presets_from_file`, `test_init_ac3_presets_file_shipped`, `test_init_ac3_dev_preset_requires_aws`; AC4 `test_init_ac4_no_secrets_in_file`; AC5 `test_init_ac5_existing_file_prompt`, `test_init_ac5_non_interactive_requires_force`, `test_init_ac5_backup_written`; AC6 `test_init_ac6_invalid_answers_reprompted` (cluster name, CIDR host bits, schedule minute); AC7 `test_init_ac7_non_interactive_matches_interactive`, `test_init_ac7_dry_run_stdout_only`, `test_init_ac7_missing_flags`; AC8 `test_init_ac8_delegates_to_import`; AC9 `test_init_ac9_plan_after_init`.
