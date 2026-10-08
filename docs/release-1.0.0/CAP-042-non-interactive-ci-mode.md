# CAP-042 — Non-interactive (CI/CD) mode for every command

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P0 | 3 | CAP-006, CAP-038 | Not started |

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
- **Approval sources** (highest first): `--auto-approve` (alias `--yes`, `-y`) → `CAPELLACTL_AUTO_APPROVE=true` → profile setting `autoApprove: true` (CAP-037). Resolved once in `AppState`. A single helper (`console.confirm(state, question, typed=None)`) is used by every command instead of calling `click.confirm` / `click.prompt` directly.
- **Questions** go through one helper (`console.ask(state, label, default, flag="--memory")`). Without a terminal it never waits for input: it uses the documented default, or exits 3 with `missing --memory (no terminal to ask; pass it on the command line)`.
- **Quiet output:** a global `--quiet` / `-q` and `CAPELLACTL_QUIET=true`. They suppress progress lines, hints and "previous version kept as …" notes. Errors, blocked reasons, the final result and `-o json` output are always printed. Exit codes are unchanged.
- **CI detection** is informational only: when `CI=true` and no approval source is set, the refusal message adds `set CAPELLACTL_AUTO_APPROVE=true in the pipeline`. CI is never treated as approval by itself.
- A static test walks the click command tree, so a new command cannot skip the helpers.

## Acceptance criteria & tests

### AC1 — One approval switch for every command
**Given** `CAPELLACTL_AUTO_APPROVE=true` and no terminal, **then** every command that changes Capella or `capella.yaml` (`apply`, `apply --prune`, `project create|update|delete`, `cluster create|update|scale|delete`, `bucket create|update|delete`, and later commands) completes without a prompt. `--auto-approve`, `--yes` and `-y` behave the same.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac1_env_approves_every_write_command` | `tests/scenario/test_ci_mode.py` | Parametrised over the command tree |
| `test_ci_ac1_flag_aliases` | same | |

### AC2 — Never waits for input without a terminal
**Given** stdin is not a terminal, **then** no command blocks on a prompt. A question with a documented default uses it; a required answer exits 3 with `missing --FLAG (no terminal to ask; pass it on the command line)`.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac2_no_command_reads_stdin` | `tests/scenario/test_ci_mode.py` | Every command with empty stdin returns before a 5 s timeout |
| `test_ci_ac2_missing_required_answer_exits_3` | same | |

### AC3 — Same refusal everywhere without approval
**Given** no terminal and no approval source, **then** every write command exits 1 with `refusing to <verb> without approval; pass --auto-approve or set CAPELLACTL_AUTO_APPROVE=true`, and makes zero writes. With `CI=true` the message also says to set the variable in the pipeline.

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
**Given** an interactive terminal and no approval source, **then** every confirmation and typed-name prompt is still asked exactly as before.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac5_terminal_still_confirms` | `tests/scenario/test_ci_mode.py` | |

### AC6 — No command bypasses the helpers
**Given** the command tree, **then** a static test fails when any command module calls `click.confirm` or `click.prompt` directly, or when a write command does not accept approval.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac6_no_direct_prompts` | `tests/unit/cli/test_prompt_helpers.py` | |

### AC7 — Idempotent pipeline re-run
**Given** a pipeline step `capellactl apply` (approval from the environment) that has completed, **then** running it again makes zero writes and exits 0, and `plan --detailed-exitcode` exits 0.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac7_rerun_zero_writes` | `tests/scenario/test_ci_mode.py` | |

### AC8 — Documented for pipelines
**Given** `capellactl help ci`, **then** it shows the approval sources, `--quiet`, exit codes for gating (`plan --detailed-exitcode`), and a GitHub Actions / GitLab CI example. The README links to it.

| Test | Location | Verifies |
|---|---|---|
| `test_ci_ac8_help_topic` | `tests/unit/cli/test_help.py` | |

## Out of scope
- Machine-readable progress events (streaming JSON lines).
- Approval policies per action type (for example "approve creates, never deletes").

## Open questions
- Should destructive actions (deletes, `--prune`, scale-in) require the explicit `--auto-approve` flag even when `CAPELLACTL_AUTO_APPROVE=true` is set, so that an inherited environment variable can never delete data?
- Should the profile setting `autoApprove` exist at all, or only the flag and the environment variable (a profile on a laptop could silence prompts by surprise)?
