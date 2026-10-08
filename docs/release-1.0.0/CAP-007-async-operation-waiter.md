# CAP-007 — Async operation waiter

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P0 | 3 | CAP-003, CAP-004 | Implemented |

## User story
As an **operator**, I want the tool to wait for long cluster operations and show progress, so that dependent steps run only when the cluster is ready and I know what is happening.

## Context & discovery
- Cluster create, update, delete and power changes return `202` and continue in the background.
- `currentState` values and their meaning per operation: [00-architecture.md §8](00-architecture.md#8-asynchronous-operations-and-cluster-states).

## Implementation details

`engine/waiter.py`:

```python
def wait_for_cluster(client, project_id, cluster_id, op: Literal["create","update","power_off","power_on","delete"],
                     timeout: timedelta, clock: Clock, on_state: Callable[[str, timedelta], None]) -> str
```

- Poll interval: 10 s, ×1.5 per poll, capped at 60 s.
- Success / failure / transitional sets per `op` from §8.
- `delete` succeeds on `NotFound`.

## Acceptance criteria & tests

### AC1 — Waits to the success state
**Given** a cluster in `deploying` that becomes `healthy` after 4 minutes, **when** waiting for `create`, **then** the waiter returns `healthy` and prints `cluster nova-dev-01: deploying (0s)` then `cluster nova-dev-01: healthy (4m0s)`.

| Test | Location | Verifies |
|---|---|---|
| `test_waiter_ac1_create_reaches_healthy` | `tests/unit/engine/test_waiter.py` | Fake clock |
| `test_waiter_ac1_prints_state_changes_only` | same | One line per state change |

### AC2 — Poll backoff
**Given** a 10-minute wait, **then** poll intervals are 10, 15, 22.5, 33.75, 50.6, 60, 60 … seconds.

| Test | Location | Verifies |
|---|---|---|
| `test_waiter_ac2_backoff_sequence` | `tests/unit/engine/test_waiter.py` | |

### AC3 — Failure state
**Given** the cluster enters `deploymentFailed` (create) or `scaleFailed` (update), **then** the waiter raises and the CLI exits 1 with `cluster nova-dev-01 entered deploymentFailed; check the Capella UI activity log`.

| Test | Location | Verifies |
|---|---|---|
| `test_waiter_ac3_failure_states` | `tests/unit/engine/test_waiter.py` | Parametrised over op → failure states |

### AC4 — Timeout
**Given** `--timeout 5m` and the cluster still `scaling`, **then** exit 5 with `cluster nova-dev-01 still scaling after 5m0s; the operation continues in Capella; re-run to resume waiting` (durations use the same `XmYs` format as AC1).

| Test | Location | Verifies |
|---|---|---|
| `test_waiter_ac4_timeout_exit_5` | `tests/scenario/test_waiter_cli.py` | |

### AC5 — No-wait
**Given** `--no-wait` on `apply` creating a cluster and buckets, **then** the cluster `POST` is sent, children are reported `… deferred (cluster deploying)`, the command exits 0, and a later `apply` without `--no-wait` waits and creates the children.

| Test | Location | Verifies |
|---|---|---|
| `test_waiter_ac5_no_wait_defers_children` | `tests/scenario/test_waiter_cli.py` | |
| `test_waiter_ac5_later_apply_completes` | same | |

### AC6 — Resume waiting, never re-issue
**Given** `apply` finds the cluster already `scaling` from an earlier run, **then** it waits and does not send another `PUT`.

| Test | Location | Verifies |
|---|---|---|
| `test_waiter_ac6_transitional_state_no_second_write` | `tests/scenario/test_waiter_cli.py` | |

### AC7 — Delete completes on 404
**Given** waiting for `delete`, **when** `GET` returns `404`, **then** the waiter returns success.

| Test | Location | Verifies |
|---|---|---|
| `test_waiter_ac7_delete_404_is_success` | `tests/unit/engine/test_waiter.py` | |

### AC8 — Interrupt
**Given** Ctrl-C while waiting, **then** exit 130 with `stopped waiting; the operation continues in Capella`.

| Test | Location | Verifies |
|---|---|---|
| `test_waiter_ac8_interrupt_message` | `tests/scenario/test_waiter_cli.py` | |

### AC9 — Heartbeat and total time
**Given** a wait longer than 30 seconds, **then** a dot is printed every 30 seconds of waiting on the same line as the current state (`cluster nova-dev-01: deploying (0s) ..`), the next line starts on a new line, and polling follows the same backoff as AC2. **When** the operation finishes, **then** the total time is shown: `done cluster nova-dev-01 in 1m21s`, the summary table's DURATION uses the same `XmYs` format, and apply ends with `Apply complete in 1m21s.`; deletes end with `cluster nova-dev-01: deleted (4m12s)`.

| Test | Location | Verifies |
|---|---|---|
| `test_waiter_ac9_tick_every_30s_same_polls` | `tests/unit/engine/test_waiter.py` | Ticks at 30, 60, …; poll gaps unchanged |
| `test_waiter_ac9_dots_and_total_time` | `tests/scenario/test_waiter_cli.py` | Apply / cluster create |
| `test_waiter_ac9_delete_dots_and_total_time` | same | `cluster delete` |

## Out of scope
- Waiting on App Service states.

## Open questions
- Does Capella expose an activity/event ID we could print for failed operations? (Events API exists; confirm usefulness in sandbox.)

## Implementation notes (as built)
- The timeout message uses the same `XmYs` duration format as AC1 (`5m0s`); AC4 text corrected.
- AC9 added 2026-10-07 after user feedback: a 10-minute deploy printed nothing between `deploying` and `healthy`. The waiter sleeps in slices so a tick lands every 30 seconds; the CLI's state line for a transitional state is left open and later output ends it (`console.err_inline`).
- Interrupting while waiting prints `stopped waiting; the operation continues in Capella`.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_waiter_ac1_progress_lines` (tests/scenario/test_waiter_cli.py)<br>`test_waiter_ac1_create_reaches_healthy` (tests/unit/engine/test_waiter.py)<br>`test_waiter_ac1_prints_state_changes_only` (tests/unit/engine/test_waiter.py) |
| AC2 | `test_waiter_ac2_backoff_sequence` (tests/unit/engine/test_waiter.py) |
| AC3 | `test_waiter_ac3_failure_states` (tests/unit/engine/test_waiter.py) |
| AC4 | `test_waiter_ac4_timeout_exit_5` (tests/scenario/test_waiter_cli.py) |
| AC5 | `test_waiter_ac5_no_wait_defers_children` (tests/scenario/test_waiter_cli.py)<br>`test_waiter_ac5_later_apply_completes` (tests/scenario/test_waiter_cli.py) |
| AC6 | `test_waiter_ac6_transitional_state_no_second_write` (tests/scenario/test_waiter_cli.py)<br>`test_waiter_ac6_update_waits_until_healthy_first` (tests/scenario/test_waiter_cli.py) |
| AC7 | `test_waiter_ac7_delete_404_is_success` (tests/unit/engine/test_waiter.py) |
| AC8 | `test_waiter_ac8_interrupt_message` (tests/scenario/test_waiter_cli.py) |
| AC9 | `test_waiter_ac9_tick_every_30s_same_polls` (tests/unit/engine/test_waiter.py)<br>`test_waiter_ac9_dots_and_total_time` (tests/scenario/test_waiter_cli.py)<br>`test_waiter_ac9_delete_dots_and_total_time` (tests/scenario/test_waiter_cli.py) |
