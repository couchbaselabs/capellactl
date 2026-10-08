# CAP-019 — Power a cluster off and on (on-demand hibernation)

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E5 Hibernation | P0 | 3 | CAP-007, CAP-011 | Implemented |

## User story
As an **operator**, I want to turn a non-production cluster off when nobody uses it and on again when needed, with one idempotent command, so that we stop paying for idle compute without losing data or configuration.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Turn on | `POST …/clusters/{clusterId}/activationState` | 202 | Body `{turnOnLinkedAppService: boolean}` (default false); `409` on conflicting state |
| Turn off | `DELETE …/clusters/{clusterId}/activationState` | 202 | `409` on conflicting state |

From the spec: turning off *"turns off the compute … but the storage remains. All of the data, schema (buckets, scopes, and collections), and indexes remain, as well as cluster configuration, including users and allow lists"*; it *"will also turn off any linked app services"*; and it *"will not stop charges being incurred for Data API"*.

States: `turningOff` → `turnedOff`; `turningOn` → `healthy`; failures `turningOffFailed`, `turningOnFailed`.

## Implementation details
```
capellactl cluster power NAME --off
capellactl cluster power NAME --on [--with-app-service]
capellactl apply --power-on       # turn on any turnedOff cluster before reconciling it
```
- `resources/power.py` reads `currentState` first; no request if already in the target state.
- `--off` confirmation text includes the three spec notes above.
- If the cluster has an active hibernation schedule (CAP-020), print `note: the on/off schedule will turn this cluster on at <next on-time>`.
- `apply` on a `turnedOff` cluster: changes to the cluster or its children are `BLOCKED (cluster is turned off; run 'capellactl cluster power NAME --on' or pass --power-on)`.

## Acceptance criteria & tests

### AC1 — Power off and wait
**Given** a `healthy` cluster, **when** `cluster power nova-dev-01 --off` is confirmed, **then** `DELETE …/activationState` is sent, the command waits for `turnedOff` and prints `cluster nova-dev-01 is off (storage, data and configuration retained)`.

| Test | Location | Verifies |
|---|---|---|
| `test_power_ac1_off_and_wait` | `tests/scenario/test_power.py` | |
| `test_endpoints_ac1_activation_state_contract` | `tests/contract/test_endpoints_cluster.py` | POST body / DELETE |

### AC2 — Power on, with or without App Service
**Given** a `turnedOff` cluster, **then** `--on` sends `POST …/activationState` with `{"turnOnLinkedAppService": false}`, and `--on --with-app-service` sends `true`; both wait for `healthy`.

| Test | Location | Verifies |
|---|---|---|
| `test_power_ac2_on_body_flag` | `tests/scenario/test_power.py` | Parametrised |

### AC3 — Already in target state
**Given** the cluster is already `turnedOff` and `--off` is requested (or `healthy` and `--on`), **then** `already off` / `already on`, exit 0, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_power_ac3_already_in_state_noop` | `tests/scenario/test_power.py` | |

### AC4 — In transition
**Given** the cluster is `turningOff` and `--off` is requested, **then** the command waits without sending a request. **Given** it is `turningOff` and `--on` is requested, **then** it waits for `turnedOff`, then sends `POST`.

| Test | Location | Verifies |
|---|---|---|
| `test_power_ac4_same_direction_waits_only` | `tests/scenario/test_power.py` | |
| `test_power_ac4_opposite_direction_waits_then_acts` | same | |

### AC5 — Conflict and failure
**Given** a `409`, **then** the state is re-read and AC3/AC4 logic applied once; a second `409` exits 1 with the API message. **Given** `turningOnFailed`, **then** exit 1 with the activity-log hint.

| Test | Location | Verifies |
|---|---|---|
| `test_power_ac5_409_rereads_state` | `tests/scenario/test_power.py` | |
| `test_power_ac5_turning_on_failed` | same | |

### AC6 — Apply against a turned-off cluster
**Given** a `turnedOff` cluster with a pending bucket change, **then** `apply` reports `! bucket … BLOCKED (cluster is turned off …)`, exit 4; **with** `--power-on`, it powers on, waits for `healthy`, then applies the bucket change.

| Test | Location | Verifies |
|---|---|---|
| `test_power_ac6_apply_turned_off_blocked` | `tests/scenario/test_power.py` | |
| `test_power_ac6_apply_power_on_flag` | same | Order: POST activation → bucket write |

### AC7 — Schedule note
**Given** an active schedule whose next on-time is Monday 08:00 US/Pacific, **when** powering off on Friday 19:00, **then** the note shows `Mon 08:00 US/Pacific`.

| Test | Location | Verifies |
|---|---|---|
| `test_power_ac7_schedule_next_on_note` | `tests/scenario/test_power.py` | `freezegun` |

### AC8 — Idempotent re-run
**Given** AC1 completed, **then** `--off` again makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_power_ac8_rerun_zero_writes` | `tests/scenario/test_power.py` | |
| `test_power_ac8_integration_cycle` | `tests/integration/test_power.py` | Off → on on sandbox |

### AC9 — Free-tier clusters
**Given** a free-tier cluster, **then** `cluster power --off|--on` (and `apply --power-on`) use `DELETE|POST …/clusters/freeTier/{clusterId}/activationState` (no body; turning on also turns on linked App Services) and wait in the same way. *(Added 2026-10-07: the API coverage report listed these endpoints as a gap with no story.)*

| Test | Location | Verifies |
|---|---|---|
| `test_power_ac9_free_tier_endpoints` | `tests/scenario/test_power.py` | |

## Out of scope
- Powering App Services independently.

## Open questions
- What happens if a power-off is requested while the schedule says "on" — does Capella's scheduler turn it straight back on at the next evaluation, or only at the next boundary? Document the observed behaviour.

## Implementation notes (as built)
- `capellactl cluster power NAME --on|--off [--with-app-service]` (`capellactl/cli/power_cmds.py`). `--off` shows the three spec notes and asks (or needs `--auto-approve`); `--on` does not ask. Power is not recorded in capella.yaml: it is not part of the environment description (the on/off schedule is).
- In transition (AC4): `turningOff` + `--off` only waits; `turningOff` + `--on` waits for `turnedOff`, then sends `POST`. With `--no-wait` a cluster in transition exits 4.
- AC5: a `409` re-reads the state once and re-decides; a second `409` exits 1 with `Capella refused: …`.
- AC6: the planner asks each ancestor whether a child change can be made (`Reconciler.child_block_reason`); a turned-off cluster blocks every change below it except its schedule, and names the next on-time from the schedule when there is one. `apply --power-on` plans `~ cluster NAME   power on` (change `power: off → on`), powers on and waits for `healthy` before anything below it is applied.
- AC7: the note is computed from the cluster's schedule (`resources/schedule.py::next_on_text`), skipped when the schedule is paused.
- AC9 added: free-tier clusters use their own activation endpoints (the API coverage report listed them as a gap).
- Waiting prints a dot every 30 seconds and the elapsed time (CAP-007 AC9).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_endpoints_ac1_activation_state_contract` (tests/contract/test_endpoints_cluster.py)<br>`test_power_ac1_off_and_wait` (tests/scenario/test_power.py) |
| AC2 | `test_power_ac2_on_body_flag` (tests/scenario/test_power.py) |
| AC3 | `test_power_ac3_already_in_state_noop` (tests/scenario/test_power.py) |
| AC4 | `test_power_ac4_same_direction_waits_only` (tests/scenario/test_power.py)<br>`test_power_ac4_opposite_direction_waits_then_acts` (tests/scenario/test_power.py) |
| AC5 | `test_power_ac5_409_rereads_state` (tests/scenario/test_power.py)<br>`test_power_ac5_turning_on_failed` (tests/scenario/test_power.py) |
| AC6 | `test_power_ac6_apply_turned_off_blocked` (tests/scenario/test_power.py)<br>`test_power_ac6_apply_power_on_flag` (tests/scenario/test_power.py) |
| AC7 | `test_power_ac7_schedule_next_on_note` (tests/scenario/test_power.py)<br>`test_power_ac7_next_on_from_friday_evening` (tests/unit/resources/test_schedule_next.py) |
| AC8 | `test_power_ac8_integration_cycle` (tests/integration/test_power.py)<br>`test_power_ac8_rerun_zero_writes` (tests/scenario/test_power.py) |
| AC9 | `test_power_ac9_free_tier_endpoints` (tests/scenario/test_power.py) |

