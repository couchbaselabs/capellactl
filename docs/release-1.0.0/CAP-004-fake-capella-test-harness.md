# CAP-004 — Fake Capella test harness

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P0 | 5 | CAP-003 | In progress |

## User story
As a **developer of capellactl**, I want an in-memory fake of the Management API that behaves like Capella (IDs, async states, ETags, conflicts, errors), so that every story's acceptance criteria can be asserted quickly and deterministically without a real organization.

## Context & discovery
- A real cluster takes minutes to deploy and costs money; scenario tests need seconds.
- Idempotency is the core promise; the harness must make "zero writes on re-run" a one-line assertion ([00-architecture.md §12.3](00-architecture.md#123-standard-assertions)).
- Behaviours to model, all taken from the API spec: `202` + `currentState` progression for clusters; `201` creates for most children; `204` updates; `ETag`/`If-Match`/`412`; `409` conflicts; `404` after delete; base64 bucket IDs; generated credential passwords returned only on create; `onOffSchedule` 404 when none exists; `stats` memory figures.

## Implementation details

`tests/fakes/capella.py`:

```python
class FakeCapella:
    def __init__(self, org_id="org-1", clock: FakeClock): ...
    def install(self, rsps: responses.RequestsMock) -> None   # registers callbacks for every endpoint
    # state seeding
    def seed_project(self, name, **fields) -> str
    def seed_cluster(self, project_id, name, state="healthy", **fields) -> str
    # behaviour switches
    def fail_next(self, method, path_glob, status, code=None, times=1)
    def set_transition(self, cluster_id, path=["deploying", "healthy"], step_seconds=60)
    # assertions
    def calls(self, method=None, path_glob=None) -> list[Call]
    def writes(self) -> list[Call]
    def reset_calls(self)
    def advance(self, seconds)
```

- Resource store: dicts keyed by ID; ETag = per-resource integer incremented on every write.
- Cluster async: create sets `deploying`; `advance()` moves to `healthy`. PUT sets `scaling` → `healthy`. Activation `DELETE` → `turningOff` → `turnedOff`. Cluster `DELETE` → `destroying` → removed (404).
- Validation subset mirrored from the spec (enums, required fields) returning `422` with `{httpStatusCode, code, message, hint}`.
- `FakeClock` is shared with the waiter (CAP-007) and `freezegun`.

## Acceptance criteria & tests

### AC1 — Covers every release endpoint
**Given** the endpoint inventory used by CAP-003 AC9, **then** the fake registers a handler for each; an unregistered call fails the test with `FakeCapella: unhandled GET /v4/…`.

| Test | Location | Verifies |
|---|---|---|
| `test_fake_ac1_handles_every_inventory_endpoint` | `tests/unit/fakes/test_fake_capella.py` | |
| `test_fake_ac1_unhandled_call_fails_loudly` | same | |

### AC2 — Realistic async cluster lifecycle
**Given** a cluster created through the fake, **then** `GET` returns `deploying` until `advance(step_seconds)`, then `healthy`; a delete goes `destroying` then `404`; power off goes `turningOff` then `turnedOff`.

| Test | Location | Verifies |
|---|---|---|
| `test_fake_ac2_create_deploying_then_healthy` | `tests/unit/fakes/test_fake_capella.py` | |
| `test_fake_ac2_delete_then_404` | same | |
| `test_fake_ac2_power_cycle_states` | same | |

### AC3 — ETags and conflicts
**Given** a `PUT` with a stale `If-Match`, **then** the fake returns `412`. **Given** a duplicate create where Capella enforces uniqueness (bucket, scope, collection, credential, CIDR), **then** it returns `409` with code `1010`. Projects and clusters allow duplicate names (as Capella does).

| Test | Location | Verifies |
|---|---|---|
| `test_fake_ac3_stale_etag_412` | `tests/unit/fakes/test_fake_capella.py` | |
| `test_fake_ac3_duplicate_child_409` | same | Parametrised per kind |
| `test_fake_ac3_duplicate_cluster_name_allowed` | same | |

### AC4 — Write recording
**Given** any scenario, **then** `fake.writes()` returns only `POST`/`PUT`/`DELETE` calls in order with method, path, JSON body (passwords redacted in the repr) and headers.

| Test | Location | Verifies |
|---|---|---|
| `test_fake_ac4_writes_excludes_gets` | `tests/unit/fakes/test_fake_capella.py` | |
| `test_fake_ac4_call_repr_redacts_password` | same | |

### AC5 — Fault injection
**Given** `fail_next("GET", "*/clusters/*", 503, times=2)`, **then** the next two matching calls return 503 and the third succeeds.

| Test | Location | Verifies |
|---|---|---|
| `test_fake_ac5_fail_next_times` | `tests/unit/fakes/test_fake_capella.py` | |

### AC6 — Parity check against real Capella
**Given** the nightly integration run (CAP-032), **then** a recorded sample of real responses (IDs and secrets scrubbed) is compared field-by-field with the fake's responses for the same operations, and new or missing fields are reported.

| Test | Location | Verifies |
|---|---|---|
| `test_fake_ac6_response_shape_parity` | `tests/integration/test_fake_parity.py` | `@pytest.mark.integration` |

## Out of scope
- Simulating Capella's real timings or billing.

## Open questions
- None.

## Implementation notes (as built)
- AC6 (response-shape parity with a real organization) is written but skipped: it needs `CAPELLA_SANDBOX_API_KEY` and `CAPELLA_SANDBOX_ORG_ID`. The story stays In progress until it runs green (planned with CAP-032).
- Extra harness features used by other stories: `fail_next(..., before=)` simulates races; `hooks` run before each request.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_fake_ac1_handles_every_inventory_endpoint` (tests/unit/fakes/test_fake_capella.py)<br>`test_fake_ac1_unhandled_call_fails_loudly` (tests/unit/fakes/test_fake_capella.py) |
| AC2 | `test_fake_ac2_create_deploying_then_healthy` (tests/unit/fakes/test_fake_capella.py)<br>`test_fake_ac2_delete_then_404` (tests/unit/fakes/test_fake_capella.py)<br>`test_fake_ac2_power_cycle_states` (tests/unit/fakes/test_fake_capella.py) |
| AC3 | `test_fake_ac3_stale_etag_412` (tests/unit/fakes/test_fake_capella.py)<br>`test_fake_ac3_duplicate_child_409` (tests/unit/fakes/test_fake_capella.py)<br>`test_fake_ac3_duplicate_cluster_name_allowed` (tests/unit/fakes/test_fake_capella.py) |
| AC4 | `test_fake_ac4_writes_excludes_gets` (tests/unit/fakes/test_fake_capella.py)<br>`test_fake_ac4_call_repr_redacts_password` (tests/unit/fakes/test_fake_capella.py) |
| AC5 | `test_fake_ac5_fail_next_times` (tests/unit/fakes/test_fake_capella.py) |
| AC6 | `test_fake_ac6_response_shape_parity` (tests/integration/test_fake_parity.py) |
