# CAP-042 — Non-interactive (CI/CD) mode for every command

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P0 | 3 | CAP-006, CAP-038 | Implemented |

## User story
As a **platform engineer running capellactl in a CI/CD pipeline**, I want one consistent way to tell every command to run without questions and with minimal output, so that pipelines never hang on a prompt, never need per-command workarounds, and their logs stay readable. At a terminal, people still get every confirmation.

## Context & discovery
As built today:
- A global `--auto-approve` flag skips confirmations. Without a terminal and without the flag, commands that change Capella refuse (exit 1), but the wording differs per command ("refusing to apply…", "refusing to delete…", "refusing to change capella.yaml…").
- Typed-name confirmations (`project delete`, `bucket delete`, each bucket in `apply --prune`) are skipped by `--auto-approve`.
- Some commands ask questions as well as confirmations: the `cluster create` wizard, `cluster update` / `bucket update` with no options, `bucket create` (memory), `project create` (description), and `configure`. Each decides on its own whether to ask, use a default or fail.
- There is no environment variable or profile setting for approval. A pipeline must add `--auto-approve` to every call.
- Progress lines (`→ creating …`, waiter states) and hints always go to stderr. There is no quiet mode.

## Implementation details
- **Approval** comes only from the global flag `--auto-approve` (aliases `--yes`, `-y`), resolved once in `AppState`. It approves every write, deletes and `--prune` included. There is no approval environment variable and no profile setting (see Open questions): approval is always explicit and visible in the command line and in pipeline logs, and a variable left set in a shell can never approve a delete. A single helper (`console.confirm(state, question, typed=None)`) is used by every command instead of calling `click.confirm` / `click.prompt` directly.
- **Questions** go through one helper (`console.ask(state, label, default, flag="--memory")`). Without a terminal it never waits for input: it uses the documented default, or exits 3 with `missing --memory (no terminal to ask; pass it on the command line)`.
- **Quiet output:** a global `--quiet` / `-q` and `CAPELLACTL_QUIET=true`. They suppress progress lines, hints and "previous version kept as …" notes. Errors, blocked reasons, the final result and `-o json` output are always printed. Exit codes are unchanged.
- **CI detection** is informational only: when `CI=true` and no approval source is set, the refusal message adds `add --auto-approve to this pipeline step`. CI is never treated as approval by itself.
- A static test walks the click command tree, so a new command cannot skip the helpers.

## Acceptance criteria & tests

### AC1 — One approval switch for every command
**Given** `--auto-approve` and no terminal, **then** every command that changes Capella or `capella.yaml` (`apply`, `apply --prune`, `project create|update|delete`, `cluster create|update|scale|delete`, `bucket create|update|delete`, and later commands) completes without a prompt. `--yes` and `-y` behave the same. Setting `CAPELLACTL_AUTO_APPROVE=true` approves nothing.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac1_flag_approves_every_write_command` | `tests/scenario/test_ci_mode.py` | Parametrised over the command tree |
| `test_ci_ac1_flag_aliases` | same | |
| `test_ci_ac1_env_var_is_not_approval` | same | Refused, zero writes |

### AC2 — Never waits for input without a terminal
**Given** stdin is not a terminal, **then** no command blocks on a prompt. A question with a documented default uses it; a required answer exits 3 with `missing --FLAG (no terminal to ask; pass it on the command line)`.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac2_no_command_reads_stdin` | `tests/scenario/test_ci_mode.py` | Every command with empty stdin returns before a 5 s timeout |
| `test_ci_ac2_missing_required_answer_exits_3` | same | |

### AC3 — Same refusal everywhere without approval
**Given** no terminal and no `--auto-approve`, **then** every write command exits 1 with `refusing to <verb> without approval; pass --auto-approve`, and makes zero writes. With `CI=true` the message also says `add --auto-approve to this pipeline step`.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac3_uniform_refusal` | `tests/scenario/test_ci_mode.py` | Parametrised; zero writes |

### AC4 — Quiet output
**Given** `--quiet` (or `CAPELLACTL_QUIET=true`), **then** stderr has no progress or hint lines on success; stdout has only the plan summary line and the result table (text) or the JSON document (`-o json`). Errors and blocked reasons are still printed, and exit codes are unchanged.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac4_quiet_success_output` | `tests/scenario/test_ci_mode.py` | |
| `test_ci_ac4_quiet_still_shows_errors` | same | |

### AC5 — Terminal behaviour unchanged
**Given** an interactive terminal and no `--auto-approve`, **then** every confirmation and typed-name prompt is still asked exactly as before.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac5_terminal_still_confirms` | `tests/scenario/test_ci_mode.py` | |

### AC6 — No command bypasses the helpers
**Given** the command tree, **then** a static test fails when any command module calls `click.confirm` or `click.prompt` directly, or when a write command does not accept approval.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac6_no_direct_prompts` | `tests/unit/cli/test_prompt_helpers.py` | |

### AC7 — Idempotent pipeline re-run
**Given** a pipeline step `capellactl --auto-approve apply` that has completed, **then** running it again makes zero writes and exits 0, and `plan --detailed-exitcode` exits 0.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac7_rerun_zero_writes` | `tests/scenario/test_ci_mode.py` | |

### AC8 — Documented for pipelines
**Given** `capellactl help ci`, **then** it shows `--auto-approve` / `--yes` / `-y`, `--quiet` / `CAPELLACTL_QUIET`, exit codes for gating (`plan --detailed-exitcode`), and a GitHub Actions / GitLab CI example. The README links to it, and the [runbook](../runbook.md) (formerly the cheatsheet) shows `-y` and `--quiet` in its intro and a short **CI/CD** section in its command reference.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac8_help_topic` | `tests/unit/cli/test_help.py` | |
| `test_ci_ac8_runbook_ci_section` | `tests/unit/docs/test_runbook_ci.py` | Section present; its commands parse |

## Out of scope
- Machine-readable progress events (streaming JSON lines).
- An approval environment variable or profile setting (decided against; see Open questions).
- Approval policies per action type (for example "approve creates, never deletes").

## Open questions
- ~~Should destructive actions require the explicit `--auto-approve` flag even when `CAPELLACTL_AUTO_APPROVE=true` is set?~~ Answered (2026-10-08): there is no approval environment variable at all. With one approval switch, the flag, the question does not arise, and an inherited variable can never approve a delete.
- ~~Should the profile setting `autoApprove` exist?~~ Answered (2026-10-08): no. A saved profile could silence prompts by surprise on a laptop.

## Implementation notes (as built)
- Helpers live in `capellactl/cli/console.py`: `confirm(state, question, verb, notes=None)` and
  `confirm_typed(state, label, verb, matches, notes=None)` for approvals; `ask(label, default, flag=…)` and
  `ask_yes_no(question, default)` for questions that are not approvals (they do not need `state`, so they take
  none); `note()` for progress, hints and "previous version kept" lines; `refusal(state, verb)` builds the one
  refusal message. Notes (such as what a project delete removes) are printed only when a person is asked.
- Questions that are not approvals keep their meaning: overwriting a non-capellactl `capella.yaml` in `import`
  or `init`, and the import offer in `configure`, use their defaults without a terminal and are not answered
  by `--auto-approve`.
- `configure` without a terminal no longer reads the API Key Token from a pipe through the hidden prompt: it
  exits 3 with `missing --api-key-stdin …`. `--api-key-stdin` is the way to pass the key from a pipe (CAP-037
  tests use it for their non-terminal cases).
- The existing exit-3 messages for `update` commands run with nothing to change (`nothing to change; pass
  --memory …`) are kept: they already name the flags.
- `-o json` on the create/update commands now prints only the JSON document (the text plan used to come first).
- Quiet output: `--quiet` keeps the plan in full when something is blocked, so the reason is visible; the
  `plan` command itself always prints the full plan.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_ci_ac1_flag_approves_every_write_command` (23 commands), `test_ci_ac1_flag_aliases`, `test_ci_ac1_env_var_is_not_approval` (tests/scenario/test_ci_mode.py) |
| AC2 | `test_ci_ac2_no_command_reads_stdin`, `test_ci_ac2_missing_required_answer_exits_3` (tests/scenario/test_ci_mode.py); `test_ci_ac2_ask_uses_default_or_names_flag` (tests/unit/cli/test_prompt_helpers.py) |
| AC3 | `test_ci_ac3_uniform_refusal` (tests/scenario/test_ci_mode.py); `test_ci_ac3_refusal_message` (tests/unit/cli/test_prompt_helpers.py) |
| AC4 | `test_ci_ac4_quiet_success_output`, `test_ci_ac4_quiet_still_shows_errors` (tests/scenario/test_ci_mode.py) |
| AC5 | `test_ci_ac5_terminal_still_confirms` (tests/scenario/test_ci_mode.py) |
| AC6 | `test_ci_ac6_no_direct_prompts`, `test_ci_ac6_write_commands_accept_approval` (tests/unit/cli/test_prompt_helpers.py) |
| AC7 | `test_ci_ac7_rerun_zero_writes` (tests/scenario/test_ci_mode.py) |
| AC8 | `test_ci_ac8_help_topic` (tests/unit/cli/test_help.py), `test_ci_ac8_runbook_ci_section` (tests/unit/docs/test_runbook_ci.py) |
