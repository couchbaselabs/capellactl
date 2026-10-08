# CAP-034 — Help command, help topics & shell completion

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P0 | 3 | CAP-001, CAP-002 | Implemented |

## User story
As a **new user of capellactl**, I want a `help` command that explains commands, concepts and every config field from the terminal, plus tab completion, so that I can use and configure the tool without leaving the shell or reading the source.

## Context & discovery
- `--help` on each command (CAP-001) covers flags but not concepts such as idempotency, scale-in checks or the hibernation schedule format.
- Config field documentation already exists in `config/schema.json` (descriptions, enums, defaults) and in the updatable/immutable table ([00-architecture.md §6.2](00-architecture.md#62-updatable-vs-immutable)); help should be generated from these, not written twice.
- Error messages are more useful when they point at the topic that explains them.

## Implementation details

### Commands
```
capellactl help                         # same as capellactl --help, plus "Getting started" and topic list
capellactl help <command> [<sub>…]      # same as capellactl <command> … --help
capellactl help topics                  # list topics with one-line summaries
capellactl help <topic>                 # read a topic
capellactl help config [<field.path>]   # config file reference, or one field
capellactl completion bash|zsh|fish     # print a shell completion script
```

### Topics (`capellactl/help/*.md`, rendered with `rich`, plain text when not a TTY)

| Topic | Content |
|---|---|
| `getting-started` | configure → init or import → validate → plan → apply |
| `config` | File layout, secret references, defaults, `.yaml`/`.yml` discovery |
| `idempotency` | Plan symbols, natural keys, what is compared, why passwords are not |
| `scaling` | Out / in / up, limits, scale-in checks, `--step` |
| `hibernation` | Power off/on, schedule format, pause/resume, quoting `on`/`off` |
| `credentials` | Basic access, generated passwords, rotation |
| `safety` | Deletion protection, prune, cascade, confirmations |
| `exit-codes` | Table from [00-architecture.md §5.3](00-architecture.md#53-exit-codes) |
| `environment` | Env vars, profiles (CAP-037), precedence |

### Field help
`help config clusters.serviceGroups.numOfNodes` prints, from the schema: description, type, allowed values/limits, default, **updatable / immutable**, the Management API field it maps to, and an example. Array indexes are optional (`clusters[0].buckets[1].replicas` = `clusters.buckets.replicas`).

### Error hints
Every `BLOCKED` reason and validation error carries a `topic` attribute; the CLI prints `See: capellactl help <topic>` after the message.

## Acceptance criteria & tests

### AC1 — help with no arguments
**Given** `capellactl help`, **then** the output contains the command list from `--help`, a `Getting started` block with the 5 steps, and the topic list; exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_help_ac1_root_help_contains_sections` | `tests/unit/cli/test_help.py` | |

### AC2 — help for a command equals --help
**Given** every command path in the click tree, **then** `capellactl help <path>` output is identical to `capellactl <path> --help`. **Given** an unknown command, **then** exit 2 with `unknown command 'scael'. Did you mean 'scale'?`.

| Test | Location | Verifies |
|---|---|---|
| `test_help_ac2_matches_dash_dash_help` | `tests/unit/cli/test_help.py` | Walks the tree |
| `test_help_ac2_unknown_command_suggestion` | same | |

### AC3 — Topics
**Given** `capellactl help topics`, **then** all 9 topics are listed with a summary; **given** `capellactl help scaling`, **then** the topic renders; plain text (no ANSI codes) when stdout is not a TTY. An unknown topic exits 2 and lists valid ones.

| Test | Location | Verifies |
|---|---|---|
| `test_help_ac3_topics_listed` | `tests/unit/cli/test_help.py` | |
| `test_help_ac3_topic_plain_when_not_tty` | same | |
| `test_help_ac3_unknown_topic` | same | |

### AC4 — Field help from the schema
**Given** `capellactl help config clusters.buckets.storageBackend`, **then** it shows `type: string`, `allowed: couchstore, magma`, `immutable after creation`, `API: storageBackend (Create Bucket)` and an example. **Given** `help config` alone, **then** it prints the field tree. **Given** an unknown path, **then** the nearest matches are suggested.

| Test | Location | Verifies |
|---|---|---|
| `test_help_config_ac4_field_details` | `tests/unit/cli/test_help_config.py` | |
| `test_help_config_ac4_tree` | same | |
| `test_help_config_ac4_unknown_path_suggestions` | same | |
| `test_help_config_ac4_every_schema_field_documented` | same | Every leaf has description and mutability |

### AC5 — Errors point to help
**Given** a blocked scale-in, **then** the output ends with `See: capellactl help scaling`; **given** a schedule validation error, **then** `See: capellactl help hibernation`.

| Test | Location | Verifies |
|---|---|---|
| `test_help_ac5_blocked_reason_has_topic` | `tests/scenario/test_help_hints.py` | Parametrised over blocked reasons |

### AC6 — Shell completion
**Given** `capellactl completion zsh`, **then** a valid completion script is printed; when sourced, `capellactl clu<TAB>` completes to `cluster`, and `capellactl cluster scale <TAB>` completes cluster names from the config file (no API call).

| Test | Location | Verifies |
|---|---|---|
| `test_completion_ac6_scripts_generated` | `tests/unit/cli/test_completion.py` | bash, zsh, fish |
| `test_completion_ac6_cluster_names_from_config` | same | Uses click `shell_complete` |

### AC7 — Help works without credentials or network
**Given** no API key and no network, **then** every `help` and `completion` command succeeds.

| Test | Location | Verifies |
|---|---|---|
| `test_help_ac7_offline_no_key` | `tests/unit/cli/test_help.py` | Socket patched to fail |

## Out of scope
- Man pages (can be generated later from the same sources).

## Open questions
- None.

## Implementation notes (as built)
- Every command group uses `SuggestingGroup`, so `capellactl cluster scael` suggests `scale`.
- Field help is generated from `capellactl/config/schema.json` (`x-mutability`, `x-api`); a test fails if any field lacks a description or mutability.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_help_ac1_root_help_contains_sections` (tests/unit/cli/test_help.py) |
| AC2 | `test_help_ac2_matches_dash_dash_help` (tests/unit/cli/test_help.py)<br>`test_help_ac2_unknown_command_suggestion` (tests/unit/cli/test_help.py) |
| AC3 | `test_help_ac3_topics_listed` (tests/unit/cli/test_help.py)<br>`test_help_ac3_topic_plain_when_not_tty` (tests/unit/cli/test_help.py)<br>`test_help_ac3_unknown_topic` (tests/unit/cli/test_help.py) |
| AC4 | `test_help_config_ac4_field_details` (tests/unit/cli/test_help_config.py)<br>`test_help_config_ac4_tree` (tests/unit/cli/test_help_config.py)<br>`test_help_config_ac4_unknown_path_suggestions` (tests/unit/cli/test_help_config.py)<br>`test_help_config_ac4_every_schema_field_documented` (tests/unit/cli/test_help_config.py) |
| AC5 | `test_help_ac5_blocked_reason_has_topic` (tests/scenario/test_help_hints.py)<br>`test_help_ac5_validation_error_has_topic` (tests/scenario/test_help_hints.py) |
| AC6 | `test_completion_ac6_scripts_generated` (tests/unit/cli/test_completion.py)<br>`test_completion_ac6_commands` (tests/unit/cli/test_completion.py)<br>`test_completion_ac6_cluster_names_from_config` (tests/unit/cli/test_completion.py) |
| AC7 | `test_help_ac7_offline_no_key` (tests/unit/cli/test_help.py) |
