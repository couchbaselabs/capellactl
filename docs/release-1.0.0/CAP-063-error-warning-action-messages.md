# CAP-063 — Every error and warning says what happened and what to do: [ERROR]/[WARNING] and [ACTION]

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P1 | 8 | CAP-006, CAP-062 | Implemented |

## User story
As an **operator running capellactl**, I want every error and warning to start with `[ERROR]:` or `[WARNING]:`,
saying what happened, followed by `[ACTION]:`, saying what I can do about it, so that I can spot problems in long
output and always know my next step.

## Context & discovery
- Requested by a customer (2026-10-30), after CAP-062 made config problems readable: messages still mix what
  happened and what to do in one sentence ("cluster X is turningOff; try again later (or drop --no-wait)"), some
  have no next step at all ("cluster(s) not found in Capella: x"), and they start differently: `Error: …`,
  `warning: …`, `Hint: …`, `Capella refused: …` or nothing.
- Errors reach the terminal in four ways, each handled once in `cli/main.py`: a `CliExit` (≈195 call sites with a
  message, all in `cli/`), a `CapellaApiError` (`api_error_exit`), a transport error, and any other exception (the
  last-resort handler). click's own usage errors ("No such option") are printed by click.
- Warnings come from four places: settings (`config/settings.py`, deprecated variables, missing profile), config
  checks (`config_warnings` in `config/crossref.py`, printed as hints), `sync`/`import` (`res.warnings`, `warnings`
  in `cli/sync.py` and `importer/`) and `configure` (a file for another organization or project).
- The plan's own lines (`!` blocked, `~`, `+`, and notes under them) are the plan's format, not messages; they stay.

## Design

### The format
```
[ERROR]: cluster nova-dev-01 is turningOff; it can be turned on only when it is turned off
[ACTION]: Wait until it is off ('capellactl cluster get nova-dev-01' shows its state), then run the command again. See 'capellactl help hibernation'.
```
```
[WARNING]: BEARER_TOKEN is deprecated
[ACTION]: Use CAPELLA_API_KEY instead, or save the key with 'capellactl configure'.
```
- `[ERROR]:` for every failure (exit codes 1, 3, 4, 5, 130); `[WARNING]:` for a message on a non-failing exit
  (0, 2) and for every warning.
- `[ACTION]:` is a full sentence in the imperative: a command to run, an option to add, or what to wait for. When the
  error has a help topic, the action ends with `See 'capellactl help TOPIC'.` (replacing the old `See: …` line).
- A message that spans several lines (config problems, CAP-062) keeps its lines indented under `[ERROR]:`. Each
  problem's own next step is labelled `action:` (was `fix:`), and `[ACTION]:` follows the list.
- Errors and warnings go to stderr. `--quiet` hides neither.

### The framework
- `CliExit(code, message, topic=None, action="")`: the `action` keyword is required for every `CliExit` that has a
  message; a test reads the source of `capellactl/` and fails on one without it.
- `cli/console.py`: `error(what, action)` and `warning(what, action)` print the two lines; `_report` and the
  exception handlers use `error`.
- `output/notice.py`: `Notice(what, action)` for warnings built outside `cli/` (settings, config checks, import,
  sync); every warning list holds `Notice`s and is printed with `warning()`.
- `api_error_exit`: the action comes from Capella's hint when it gives one, else from the status: 401 (the key),
  403 (the roles it needs), 404 (it no longer exists: `sync`), 409/422 (the value Capella named), 429 and 5xx (try
  again; finished steps are not repeated).
- click usage errors (`No such option`, `Missing argument`, `Invalid value`, unknown command) print
  `[ERROR]:` with click's message and `[ACTION]: Run 'capellactl … --help' to see …`.

## Acceptance criteria & tests

### AC1 — Errors from capellactl
**Given** a command that fails with a `CliExit` (for example `cluster power NAME` with neither `--on` nor `--off`),
**then** stderr is `[ERROR]: …` then `[ACTION]: …`, the action ends with the help topic when there is one, and no line
starts with `Error:` or `See:`. Every `CliExit` with a message in the source has an `action`.

| Test | Location | Verifies |
|---|---|---|
| `test_messages_ac1_cli_exit_format` | `tests/unit/cli/test_messages.py` | Two lines, topic in the action |
| `test_messages_ac1_every_cli_exit_has_action` | same | Source scan |

### AC2 — Errors from Capella, the network and unexpected failures
**Given** a 403 from Capella, a 404, a 500 after retries, a transport error and an unexpected exception, **then**
each prints `[ERROR]:` with what happened (Capella's message) and `[ACTION]:` with Capella's hint or the step for
that status; the unexpected one says to run again with `--log-level debug`.

| Test | Location | Verifies |
|---|---|---|
| `test_messages_ac2_api_errors` | `tests/unit/cli/test_messages.py` | Parametrised over the statuses |
| `test_messages_ac2_transport_and_unexpected` | same | |

### AC3 — Warnings
**Given** `BEARER_TOKEN` set, a config with an expired allowed IP range, and a `sync` that keeps a turned-off
cluster's buckets, **then** each warning prints `[WARNING]: …` then `[ACTION]: …`, and no line starts with
`warning:`.

| Test | Location | Verifies |
|---|---|---|
| `test_messages_ac3_warnings` | `tests/scenario/test_messages.py` | Settings, config and sync warnings |

### AC4 — Config problems
**Given** a capella.yaml with a problem, **then** the output is `[ERROR]: capella.yaml has 1 problem:`, the problem
block with its `action:` line, then `[ACTION]:`.

| Test | Location | Verifies |
|---|---|---|
| `test_messages_ac4_config_problems` | `tests/scenario/test_messages.py` | |

### AC5 — click usage errors
**Given** `capellactl cluster create x --nope` and `capellactl clustr`, **then** stderr has `[ERROR]:` with click's
message (and the suggestion) and `[ACTION]:` naming `--help` for that command, and the exit code is click's (2).

| Test | Location | Verifies |
|---|---|---|
| `test_messages_ac5_usage_errors` | `tests/scenario/test_messages.py` | |

### AC6 — Config warnings only where they help
**Given** a capella.yaml that is valid but has settings that may not be intended (an any-IP range not recorded as
intended, an expired range, low IOPS, a credential for all buckets), **then** `validate` prints each one as
`[WARNING]`/`[ACTION]`, `plan` and `apply` print one line, `[WARNING]: capella.yaml has N settings that may not be
intended` with `[ACTION]: Run 'capellactl validate' to see them.`, and every other command (for example
`cidr list`, `cluster backup schedule options`) prints none of them.

| Test | Location | Verifies |
|---|---|---|
| `test_messages_ac6_config_warnings_only_where_relevant` | `tests/scenario/test_messages.py` | validate, plan, another command |

### AC7 — No story numbers in what users see
**Given** any command's `--help`, any message, a `help` topic or the capella.yaml schema descriptions, **then** none
of them shows a story number (`CAP-057 AC4`): those are for the people who build capellactl, and stay in comments,
internal docstrings and tests.

| Test | Location | Verifies |
|---|---|---|
| `test_messages_ac7_no_story_ids_shown` | `tests/unit/cli/test_messages.py` | Every command's help, string literals, schema, help topics |

## Out of scope
- The plan's own lines (`!`, `~`, `+`, `-` and the notes under them).
- `-o json` error documents.

## Implementation notes (as built)
- `CliExit` gained `action`; all 195 `CliExit` calls with a message in `cli/` give one. Many old messages carried the
  next step after a `;` ("…; pass --project NAME", "…; try again later"): the step moved to `action`, so `[ERROR]`
  says only what happened. Messages that already named a command keep it in the action.
- `WaitFailed`, `WaitTimeout`, `StatusFailed` and `StatusTimeout` carry `what` and `action`; their `str()` is
  unchanged for the plan and the apply summary table.
- `rejection_help` (configure) returns (what, checklist); the checklist is the multi-line `[ACTION]`. Continuation
  lines of `[ERROR]`/`[ACTION]` are indented by two spaces unless they bring their own indentation (config problem
  blocks).
- Warnings: `output/notice.py` `Notice(what, action)` is used by settings, config checks (`Config.warnings`, no longer
  mixed into hints), import and sync; `RunContext.warn(what, action)` for warnings during apply (any-IP range, a range
  replaced in place, a credentials folder that is not git-ignored, which used to be progress text).
- CAP-062's per-problem `fix:` line is now `action:`, and the "Fix them, then run the command again" sentence moved
  from the heading to `[ACTION]`.
- click usage errors: `RootGroup.main` runs click in non-standalone mode and prints click's usage line, then
  `[ERROR]`/`[ACTION]`; exit codes are click's (2 for usage, 1 for Abort).
- Found on the way: three more messages asked for hand edits ("pin the one to delete with id: in capella.yaml" twice,
  "change them in capella.yaml and run apply"); they now give commands. A location in a config problem shortens a
  name over 40 characters, so a too-long name does not fill the line.
- Tests: AC1 `test_messages_ac1_cli_exit_format`, `test_messages_ac1_every_cli_exit_has_action`; AC2
  `test_messages_ac2_api_errors` (8 cases), `test_messages_ac2_transport_and_unexpected`; AC3
  `test_messages_ac3_warnings`; AC4 `test_messages_ac4_config_problems`; AC5 `test_messages_ac5_usage_errors` (3 cases).
  About 100 existing assertions were updated to the new wording.
- AC6 (2026-10-30, customer report): config warnings were printed by every command that loads capella.yaml, so a
  read-only command such as `cluster backup schedule options test-01` started with a dozen warnings about other
  clusters. `AppState.load_config(warnings=)` now takes "all" (validate), "count" (plan, apply: one line pointing to
  validate; the plan itself already marks blocked any-IP ranges, expired ranges and all-bucket credentials) or "none"
  (the default). Test: `test_messages_ac6_config_warnings_only_where_relevant`.
- AC7 (2026-10-30, customer report): command docstrings are click's help text, so 36 of them showed story numbers
  (`List bucket backups … (CAP-059 AC1).`); two plan messages said `scale out (CAP-015)` (now `scale out with
  'capellactl cluster scale'`), the placeholder plan line named its story, and two schema descriptions named theirs.
  All removed; the unused `env.not_yet` ("planned in CAP-…") was deleted.
