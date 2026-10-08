# CAP-020 — Hibernation schedule (on/off schedule) as code

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E5 Hibernation | P0 | 5 | CAP-011 | Implemented |

## User story
As an **operator**, I want to declare when a cluster should be on (for example weekdays 08:00–18:00) and have Capella turn it off the rest of the time, so that development and test clusters hibernate automatically and cost less.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Get | `GET …/clusters/{clusterId}/onOffSchedule` | 200 | `{activationStatus: active|paused, timezone, days[]}`; `404` when none |
| Create | `POST …/clusters/{clusterId}/onOffSchedule` | **204** | `409` if one exists |
| Update | `PUT …/clusters/{clusterId}/onOffSchedule` | 204 | `412` on stale ETag |
| Delete | `DELETE …/clusters/{clusterId}/onOffSchedule` | 204 | |

Body: `timezone*` (enum of 27 values: `US/Pacific`, `US/Eastern`, `Europe/London`, `Asia/Calcutta`, `Australia/Sydney`, …) and `days*` — rules from the spec:
- exactly **7** entries, in order **Monday → Sunday**;
- each `{day*, state*: on|off|custom, from?, to?}`;
- `on`/`off` days **must not** have `from`/`to`;
- `custom` days **must** have `from`; `to` defaults to `00:00`, which means "until end of day";
- `hour` 0–23; `minute` **0 or 30** only;
- `from` must not be later than `to` (except `to` = 00:00 end of day);
- the cluster **cannot be off every day of the week**.

## Implementation details

### Config (friendly form)
```yaml
clusters:
  - name: nova-dev-01
    hibernation:
      timezone: US/Pacific
      weekdays: "08:00-18:00"     # monday–friday, custom on-window
      weekend: "off"              # saturday, sunday (quote on/off, see AC10)
      # per-day overrides win over weekdays/weekend:
      friday: "08:00-14:30"
      # wednesday: on            # whole day on
      # paused: false            # CAP-021
      # ensure: absent           # delete the schedule
```
Each day value is `on`, `off`, or `"HH:MM-HH:MM"`; `"08:00-24:00"` is accepted and sent as `to: 0:00`.

### Expansion (`resources/schedule.py::expand`)
Friendly form → API form: 7 entries Monday→Sunday; `on`/`off` without boundaries; windows → `custom` with `from`/`to` `{hour, minute}`. Comparison is done on the expanded form, so either form in the file gives the same plan.

### CLI
```
capellactl cluster schedule show NAME     # weekly grid + next transition
capellactl cluster schedule set NAME --timezone TZ --weekdays HH:MM-HH:MM --weekend off   # record + apply (added)
capellactl cluster schedule apply NAME    # reconcile only the schedule
capellactl cluster schedule delete NAME
```
`show` output:
```
nova-dev-01  US/Pacific  active
Mon ████████░░  08:00–18:00
…
Sat ░░░░░░░░░░  off
Next: off at Fri 14:30 US/Pacific
```

### Plan
```
+ schedule nova-dev-01  US/Pacific · Mon–Thu 08:00–18:00 · Fri 08:00–14:30 · Sat–Sun off
~ schedule nova-dev-01
    friday:  08:00–18:00 → 08:00–14:30
```

## Acceptance criteria & tests

### AC1 — Friendly form expands to the API form
**Given** the config above, **then** `expand()` returns 7 entries Monday→Sunday: Mon–Thu `custom 8:00–18:00`, Fri `custom 8:00–14:30`, Sat/Sun `off`, none with boundaries on `off` days.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_expand_ac1_friendly_to_api` | `tests/unit/resources/test_schedule_expand.py` | Exact JSON |
| `test_schedule_expand_ac1_override_wins` | same | |
| `test_schedule_expand_ac1_end_of_day_24_00` | same | `to: {hour:0, minute:0}` |

### AC2 — Offline validation of the API rules
**Given** each invalid input, **then** `validate` exits 3 with a specific message: minute `15`; hour `24` in `from`; `from` later than `to`; all 7 days `off`; unknown timezone `America/Denver`; window on a day also set to `on`.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_validate_ac2_rules` | `tests/unit/config/test_schedule_rules.py` | Parametrised |

### AC3 — Create when none exists
**Given** `GET …/onOffSchedule` returns `404`, **then** the plan shows `+ schedule …`, and one `POST` with the expanded body is sent (expect `204`).

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_ac3_create_when_missing` | `tests/scenario/test_schedule.py` | |
| `test_endpoints_ac3_schedule_contract` | `tests/contract/test_endpoints_schedule.py` | POST/PUT/GET/DELETE |

### AC4 — Update only the difference
**Given** an existing schedule differing only on Friday, **then** the plan shows only `friday:` and one `PUT` is sent with all 7 days and `If-Match`.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_ac4_update_full_body_minimal_diff` | `tests/scenario/test_schedule.py` | |

### AC5 — Equivalent forms are equal
**Given** Capella holds the schedule in API form and the file uses the friendly form for the same week, **then** `=` and zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_ac5_friendly_equals_api_noop` | `tests/scenario/test_schedule.py` | |

### AC6 — Absent vs remove
**Given** no `hibernation` key, **then** an existing schedule is left alone (reported as unmanaged by `drift`). **Given** `hibernation: {ensure: absent}`, **then** `- schedule nova-dev-01` and `DELETE …/onOffSchedule`; when none exists, no write.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_ac6_omitted_untouched` | `tests/scenario/test_schedule.py` | |
| `test_schedule_ac6_ensure_absent_deletes` | same | |
| `test_schedule_ac6_ensure_absent_when_none_noop` | same | |

### AC7 — Show command and next transition
**Given** the schedule above and current time Friday 13:00 US/Pacific, **then** `schedule show` prints the 7-day grid and `Next: off at Fri 14:30 US/Pacific`; `-o json` includes `nextTransition: {state, at}` in ISO 8601.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_show_ac7_grid_and_next` | `tests/scenario/test_schedule_cli.py` | `freezegun` |
| `test_schedule_next_ac7_across_week_boundary` | `tests/unit/resources/test_schedule_next.py` | Sunday → Monday |

### AC8 — Apply when the schedule has turned the cluster off
**Given** the schedule has the cluster `turnedOff` and only the schedule changes, **then** the schedule update is applied (it does not need the cluster on); other cluster/child changes are BLOCKED as in CAP-019 AC6, with the next on-time shown.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_ac8_update_while_turned_off` | `tests/scenario/test_schedule.py` | |

### AC9 — Idempotent re-run
**Given** AC3 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_ac9_rerun_zero_writes` | `tests/scenario/test_schedule.py` | |
| `test_schedule_ac9_integration` | `tests/integration/test_schedule.py` | Create → re-run → update → delete on sandbox |

### AC10 — Unquoted on/off in YAML
**Given** `weekend: off` or `wednesday: on` written without quotes (which YAML 1.1 loads as booleans `false`/`true`), **then** the loader treats them as `off`/`on` for schedule day keys only, and `validate` prints a one-time hint `tip: quote "on"/"off" in hibernation to avoid YAML boolean conversion`.

| Test | Location | Verifies |
|---|---|---|
| `test_schedule_expand_ac10_yaml_booleans` | `tests/unit/resources/test_schedule_expand.py` | `False` → `off`, `True` → `on` |
| `test_schedule_validate_ac10_quote_hint` | `tests/unit/config/test_schedule_rules.py` | |

## Out of scope
- One-off date exceptions (holidays); not supported by the API.
- Schedules for App Services.

## Open questions
- Does the schedule `GET` return an `ETag` (the `PUT` documents `412`)? If not, skip `If-Match` for schedules.
- Is the schedule's `timezone` independent of `support.timezone`? (Assumed yes.)

## Implementation notes (as built)
- `resources/schedule.py`: `expand()` (friendly → API form), the `schedule` reconciler (a cluster child, after deletion protection), the weekly grid and next-transition helpers. Days not given are `on`; `weekdays`/`weekend` fill their days, per-day keys override them.
- **Added `capellactl cluster schedule set NAME --timezone TZ --weekdays HH:MM-HH:MM --weekend off [--monday … --sunday]`**: the story's `apply` needed the schedule to be written in capella.yaml by hand, which the tool no longer asks of anyone (CAP-038). `set` records the friendly form (day values quoted, so `off` never loads as a boolean) and applies it. `schedule delete` deletes it in Capella and removes `hibernation` from the file.
- Plan lines: `+ schedule NAME  US/Pacific · Mon–Thu 08:00–18:00 · Fri 08:00–14:30 · Sat–Sun off`; updates list only the days that differ (`friday:  "08:00–18:00" → "08:00–14:30"`); the `PUT` always carries all 7 days and `If-Match` (the schedule `GET` returns an `ETag`).
- AC6: without a `hibernation` key an existing schedule is never changed; `plan` lists it under *Unmanaged* and `apply --prune` deletes it (CAP-031).
- AC7: `show` draws 24 hourly cells per day (█ on, ░ off); a cell shows the state at the start of that hour. Timezones use the OS tz database (`zoneinfo`); without one the next-transition line is left out.
- AC8: schedule changes are applied while the cluster is `turnedOff`; everything else below it is blocked (CAP-019 AC6).
- Validation also requires `timezone` (unless `ensure: absent`) and refuses a week that is off every day.
- `--target schedule/NAME` now selects the cluster above it (a schedule's key is its cluster's name).
- `import`/`sync` write a schedule as `weekdays`/`weekend` with the most common value plus per-day overrides, the same form `schedule set` writes, so `sync` right after `set` finds nothing to change (CAP-036 AC7 revised).

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_schedule_expand_ac1_friendly_to_api` (tests/unit/resources/test_schedule_expand.py)<br>`test_schedule_expand_ac1_override_wins` (tests/unit/resources/test_schedule_expand.py)<br>`test_schedule_expand_ac1_end_of_day_24_00` (tests/unit/resources/test_schedule_expand.py) |
| AC2 | `test_schedule_validate_ac2_rules` (tests/unit/config/test_schedule_rules.py) |
| AC3 | `test_endpoints_ac3_schedule_contract` (tests/contract/test_endpoints_schedule.py)<br>`test_schedule_ac3_create_when_missing` (tests/scenario/test_schedule.py)<br>`test_schedule_set_ac3_records_and_creates` (tests/scenario/test_schedule_cli.py) |
| AC4 | `test_schedule_ac4_update_full_body_minimal_diff` (tests/scenario/test_schedule.py) |
| AC5 | `test_schedule_ac5_friendly_equals_api_noop` (tests/scenario/test_schedule.py) |
| AC6 | `test_schedule_ac6_omitted_untouched` (tests/scenario/test_schedule.py)<br>`test_schedule_ac6_ensure_absent_deletes` (tests/scenario/test_schedule.py)<br>`test_schedule_ac6_ensure_absent_when_none_noop` (tests/scenario/test_schedule.py)<br>`test_schedule_delete_ac6_removes_from_capella_and_file` (tests/scenario/test_schedule_cli.py) |
| AC7 | `test_schedule_show_ac7_grid_and_next` (tests/scenario/test_schedule_cli.py)<br>`test_schedule_next_ac7_across_week_boundary` (tests/unit/resources/test_schedule_next.py) |
| AC8 | `test_schedule_ac8_update_while_turned_off` (tests/scenario/test_schedule.py) |
| AC9 | `test_schedule_ac9_integration` (tests/integration/test_schedule.py)<br>`test_schedule_ac9_rerun_zero_writes` (tests/scenario/test_schedule.py) |
| AC10 | `test_schedule_validate_ac10_quote_hint` (tests/unit/config/test_schedule_rules.py)<br>`test_schedule_expand_ac10_yaml_booleans` (tests/unit/resources/test_schedule_expand.py) |

