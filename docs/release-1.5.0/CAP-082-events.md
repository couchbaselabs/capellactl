# CAP-082 — Events

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E15 Observability & cost | P1 | 3 | CAP-003, CAP-038 | Not started |

## User story
As an **operator**, I want to list and filter Capella's activity events from the terminal, so that I can see what
happened to a cluster (scaling, failures, user actions) while I troubleshoot, without the UI.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| List (org) | `GET {org}/events` | 200 | Filters: `userIds`, `clusterIds`, `projectIds`, `severityLevels`, `tags`, `from`, `to`; paginated and sortable |
| Get (org) | `GET {org}/events/{eventId}` | 200 | |
| List (project) | `GET …/projects/{p}/events` | 200 | Same filters without `projectIds` |
| Get (project) | `GET …/projects/{p}/events/{eventId}` | 200 | |

Each event: `id`, `timestamp`, `severity`, `source`, `key`, `summary`, `projectName`, `clusterName`,
`userEmail`, `kv`, `occurrenceCount`, `alertKey`.

## Design
```
capellactl event list [--project NAME] [--cluster NAME …] [--severity critical|warning|info …] [--since DURATION | --from TIME] [--to TIME] [--limit N] [--follow]
capellactl event get  ID [--project NAME]
```
Example:
```
capellactl event list --cluster nova-dev-01 --since 24h
```
- Names are resolved to IDs; with `--project` the project endpoints are used, otherwise the organization ones.
- `--since 24h` is converted to `from`; the default is the last 24 hours, newest first, 50 rows.
- `--follow` polls every 30 s and prints new events until interrupted (exit 130).
- Read-only. Code: `cli/event_cmds.py`, four operations, fake Capella with seeded events.

## Acceptance criteria & tests

### AC1 — List with filters
**Given** `event list --cluster nova-dev-01 --since 24h`, **then** one `GET {org}/events` with `clusterIds` and `from`;
the table prints `S.NO`, `TIME`, `SEVERITY`, `SUMMARY`, `CLUSTER`, `USER`, `ID`.

| Test | Location | Verifies |
|---|---|---|
| `test_event_ac1_list_filters` | `tests/scenario/test_events.py` | Query string, columns |

### AC2 — Project scope and get
**Given** `--project nova`, **then** the project endpoint is used; `event get ID` prints every field and `kv`.

| Test | Location | Verifies |
|---|---|---|
| `test_event_ac2_project_and_get` | `tests/scenario/test_events.py` | |

### AC3 — Pagination and follow
**Given** more events than one page, **then** `--limit` pages through them (CAP-003 pagination); `--follow` prints
only new events on each poll.

| Test | Location | Verifies |
|---|---|---|
| `test_event_ac3_pagination_follow` | `tests/scenario/test_events.py` | |

### AC4 — Read-only and JSON
**Given** any run, **then** zero writes; `-o json` returns Capella's `data` array.

| Test | Location | Verifies |
|---|---|---|
| `test_event_ac4_read_only_json` | `tests/scenario/test_events.py` | |

## Out of scope
- Acknowledging or closing alerts (not in the API).

## Open questions
- What are the valid `severityLevels` and `tags` values? The spec lists them as strings; use what the sandbox
  returns.
