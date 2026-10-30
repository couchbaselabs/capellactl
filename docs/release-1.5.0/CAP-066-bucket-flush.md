# CAP-066 — Flush a bucket

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E11 Data access & tools | P1 | 2 | CAP-023, CAP-024, CAP-013 | Not started |

## User story
As a **developer**, I want to empty a test bucket without deleting and recreating it, so that I can reset test data
quickly while keeping the bucket's settings, scopes, collections and credentials.

## Context & discovery
- `PUT …/clusters/{clusterId}/buckets/{bucketId}/flush` → 200. Capella flushes only buckets created with
  `flush: true` (CAP-023 field `flush`).
- CAP-024 deliberately left flush out of 1.0.0 because it deletes every document. This story adds it with the same
  safety as `bucket delete`.

## Design
```
capellactl bucket flush CLUSTER NAME [--project NAME]
```
Example:
```
capellactl bucket flush nova-dev-01 test-orders
```
- Shows `bucket nova-dev-01/test-orders · 1,204 items will be deleted`, and asks for the bucket name to be typed
  (`--auto-approve` skips it; refused without a terminal, as CAP-024).
- Never reached from `apply`: flushing is not a desired state.
- Code: `cli/bucket_cmds.py` gains `flush`; one operation in `api/endpoints.py`; the fake empties `stats.itemCount`.

## Acceptance criteria & tests

### AC1 — Flush with typed confirmation
**Given** bucket `test-orders` with `flush: true` and 1,204 items, **then** the prompt shows the item count, typing
the name sends one `PUT …/flush` and prints `flushed bucket nova-dev-01/test-orders`.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_flush_ac1_confirm_and_flush` | `tests/scenario/test_bucket_flush.py` | Also wrong name cancels |

### AC2 — Flush not enabled
**Given** `flush: false`, **then** exit 4 `flush is not enabled on bucket test-orders; enable it with bucket update
--flush`, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_flush_ac2_not_enabled_blocked` | `tests/scenario/test_bucket_flush.py` | |

### AC3 — Protected cluster
**Given** deletion protection on, **then** exit 4 with the CAP-013 message, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_flush_ac3_protection_blocks` | `tests/scenario/test_bucket_flush.py` | |

### AC4 — Empty bucket
**Given** a bucket with 0 items, **then** `bucket is already empty`, exit 0, zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_bucket_flush_ac4_empty_noop` | `tests/scenario/test_bucket_flush.py` | |

## Out of scope
- Flushing from `apply`.

## Open questions
- None.
