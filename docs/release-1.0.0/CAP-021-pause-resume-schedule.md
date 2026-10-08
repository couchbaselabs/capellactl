# CAP-021 — Pause & resume the hibernation schedule

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E5 Hibernation | P1 | 2 | CAP-020 | Implemented |

## User story
As an **operator**, I want to pause a cluster's hibernation schedule for a demo, load test or out-of-hours incident and resume it afterwards, without deleting and recreating the schedule, so that the cluster stays on exactly as long as needed.

## Context & discovery

| Operation | Endpoint | Success |
|---|---|---|
| Pause | `DELETE …/clusters/{clusterId}/onOffSchedule/activationState` | 204 |
| Resume (unpause) | `POST …/clusters/{clusterId}/onOffSchedule/activationState` | 204 |
| Current status | `GET …/onOffSchedule` → `activationStatus: active|paused` | 200 |

## Implementation details
```
capellactl cluster schedule pause  NAME [--power-on]
capellactl cluster schedule resume NAME
```
Declarative: `hibernation.paused: true|false` (omit = leave unchanged).

`--power-on` on pause also turns the cluster on (CAP-019) if it is `turnedOff`, which is the common incident case.

## Acceptance criteria & tests

### AC1 — Pause
**Given** an `active` schedule, **then** `schedule pause nova-dev-01` sends `DELETE …/onOffSchedule/activationState` and prints `schedule paused; cluster will stay in its current state (off) until resumed`.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_pause_ac1_pause` | `tests/scenario/test_schedule_pause.py` | |
| `test_endpoints_ac1_schedule_activation_contract` | `tests/contract/test_endpoints_schedule.py` | |

### AC2 — Resume
**Given** a `paused` schedule, **then** `schedule resume` sends `POST …/onOffSchedule/activationState` and prints the next transition (CAP-020 AC7).

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_pause_ac2_resume_prints_next` | `tests/scenario/test_schedule_pause.py` | |

### AC3 — Already in the requested state
**Given** the schedule is already `paused` (or `active`), **then** pause (or resume) prints `already paused` (`already active`), exit 0, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_pause_ac3_noop_when_already` | `tests/scenario/test_schedule_pause.py` | Parametrised |

### AC4 — No schedule
**Given** `GET …/onOffSchedule` returns `404`, **then** `cluster nova-dev-01 has no on/off schedule`, exit 4.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_pause_ac4_no_schedule` | `tests/scenario/test_schedule_pause.py` | |

### AC5 — Pause with power-on
**Given** the cluster is `turnedOff` and `--power-on`, **then** the order is pause → power on → wait `healthy`.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_pause_ac5_power_on_order` | `tests/scenario/test_schedule_pause.py` | |

### AC6 — Declarative paused flag
**Given** `hibernation.paused: true` and the schedule is `active`, **then** `~ schedule nova-dev-01  activationStatus: active → paused` and the pause call is made after any schedule `POST`/`PUT`. **Given** `paused` omitted, **then** the status is never changed.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_pause_ac6_declarative_paused` | `tests/scenario/test_schedule_pause.py` | |
| `test_schedule_pause_ac6_omitted_untouched` | same | |

### AC7 — Recorded in capella.yaml
**Given** the operator pauses (or resumes) with the command, **then** capella.yaml records `paused: true` (or the key is removed), so the next `apply` keeps it and `sync` finds nothing to change. *(Revised 2026-10-07: it used to print a drift note and leave the file stale.)*

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_pause_ac7_recorded_in_file` | `tests/scenario/test_schedule_pause.py` | |

## Out of scope
- Timed pause (`--until`); the API has no such option. A cron-driven `resume` is documented in the runbook instead (CAP-033).

## Open questions
- Does a paused schedule keep the cluster in whatever state it was in at pause time? (Assumed yes; confirm.)

## Implementation notes (as built)
- `capellactl cluster schedule pause NAME [--power-on]` and `resume NAME` (`capellactl/cli/schedule_cmds.py`); `--power-on` powers the cluster on after pausing (CAP-019).
- **AC7 revised:** instead of a drift note, `pause` records `paused: true` in capella.yaml and `resume` removes it (as `import` writes an active schedule), so the next `apply` keeps what the command did, the same rule as `cluster protect` (CAP-013 AC5).
- AC6: `hibernation.paused` is compared with `activationStatus`; a new schedule is created active and paused right after the `POST`.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_endpoints_ac1_schedule_activation_contract` (tests/contract/test_endpoints_schedule.py)<br>`test_schedule_pause_ac1_pause` (tests/scenario/test_schedule_pause.py) |
| AC2 | `test_schedule_pause_ac2_resume_prints_next` (tests/scenario/test_schedule_pause.py) |
| AC3 | `test_schedule_pause_ac3_noop_when_already` (tests/scenario/test_schedule_pause.py) |
| AC4 | `test_schedule_pause_ac4_no_schedule` (tests/scenario/test_schedule_pause.py) |
| AC5 | `test_schedule_pause_ac5_power_on_order` (tests/scenario/test_schedule_pause.py) |
| AC6 | `test_schedule_pause_ac6_declarative_paused` (tests/scenario/test_schedule_pause.py)<br>`test_schedule_pause_ac6_omitted_untouched` (tests/scenario/test_schedule_pause.py)<br>`test_schedule_pause_ac6_paused_after_create` (tests/scenario/test_schedule_pause.py) |
| AC7 | `test_schedule_pause_ac7_recorded_in_file` (tests/scenario/test_schedule_pause.py) |

