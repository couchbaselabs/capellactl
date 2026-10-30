# CAP-085 — Operational Insights on/off schedule

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E16 Operational Insights | P2 | 3 | CAP-084, CAP-020 | Not started |

## User story
As an **operator**, I want an Operational Insights cluster to turn itself off out of hours on a weekly schedule, so
that analytics environments cost nothing while nobody uses them.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Get | `GET …/operationalInsightsClusters/{id}/onOffSchedule` | 200 | `timezone`, `days[]` (`day`, `state` `on`/`off`/`custom`, `from`, `to`) |
| Create | `POST …/onOffSchedule` | 204 | Same body |
| Update | `PUT …/onOffSchedule` | 204 | Same body |
| Delete | `DELETE …/onOffSchedule` | 204 | |

The body is the same as the database cluster's on/off schedule (CAP-020); there is no pause/resume.

## Design
```
capellactl insights schedule show   NAME
capellactl insights schedule set    NAME --timezone TZ --weekdays HH:MM-HH:MM [--weekends off|on|HH:MM-HH:MM]
capellactl insights schedule delete NAME
```
Example:
```
capellactl insights schedule set nova-insights --timezone Europe/London --weekdays 08:00-19:00 --weekends off
```
```yaml
insightsClusters:
  - name: nova-insights
    hibernation:                # same block as clusters[].hibernation (CAP-020)
      timezone: Europe/London
      weekdays: {from: "08:00", to: "19:00"}
      weekends: off
```
- Reuses CAP-020's schedule model, compact syntax, validation and weekly grid output; only the endpoints differ.
- Code: `cli/insights_cmds.py` gains `schedule`; `resources/insights_schedule.py`; four operations.

## Acceptance criteria & tests

### AC1 — Set
**Given** the example, **then** one `POST` (no schedule yet) or `PUT` (one exists) with seven `days`, capella.yaml
records `hibernation`, and `plan` reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_schedule_ac1_set` | `tests/scenario/test_insights_schedule.py` | |

### AC2 — Idempotent
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_schedule_ac2_rerun_zero_writes` | `tests/scenario/test_insights_schedule.py` | |

### AC3 — Validation
**Given** a timezone not in the spec's list or an invalid time range, **then** exit 3 with the CAP-020 messages.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_schedule_ac3_validation` | `tests/scenario/test_insights_schedule.py` | |

### AC4 — Show and delete
**Given** a schedule, **then** `show` prints the weekly grid and the next transition; `delete` asks once, sends one
`DELETE` and removes the block; with none, `no schedule`, exit 0.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_schedule_ac4_show_delete` | `tests/scenario/test_insights_schedule.py` | |

### AC5 — sync and drift
**Given** a schedule in Capella, **then** `sync` writes it and `drift` reports differences.

| Test | Location | Verifies |
|---|---|---|
| `test_insights_schedule_ac5_sync_drift` | `tests/scenario/test_insights_schedule.py` | |

## Out of scope
- Pause/resume (not in the API for Operational Insights).

## Open questions
- None.
