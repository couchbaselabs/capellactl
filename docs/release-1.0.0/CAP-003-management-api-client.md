# CAP-003 — Management API client: auth, retries, rate limits, pagination & errors

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P0 | 5 | CAP-001 | Implemented |

## User story
As a **developer of capellactl**, I want one HTTP client that handles authentication, retries, rate limits, pagination, ETags and errors, so that resource code only expresses business logic.

## Context & discovery
- Base URL `https://cloudapi.cloud.couchbase.com`; all paths start `/v4/organizations/{organizationId}`.
- Every endpoint documents `429` ("client exceeds the rate limit for the given APIKey"); no rate number is published in the spec, so the client relies on backoff and `Retry-After`.
- Error body schema `Error`: required `httpStatusCode`, `code`, `message`, `hint`. Example conflict: `code: 1010`, `message: There is a conflict with the current state of a resource.`
- List endpoints take `page`, `perPage`, `sortBy`, `sortDirection`, and list responses carry `cursor.pages` (`page`, `next`, `previous`, `last`, `perPage`, `totalItems`); `next` is absent on the last page.
- `GET` responses for projects, clusters, credentials and collections return an `ETag` header; their `PUT`s accept `If-Match` and return `412` on mismatch.
- Cluster create returns `202`; most other creates return `201`.

## Implementation details

| Module | Responsibility |
|---|---|
| `api/client.py` | `CapellaClient(base_url, api_key, org_id)`; `request(method, path, json=None, if_match=None) -> Response`; retry loop; pagination helper `paginate(path)` that follows `cursor.pages.next` |
| `api/errors.py` | `CapellaApiError(http_status, code, message, hint, method, path)`; subclasses `NotFound`, `Conflict`, `PreconditionFailed`, `RateLimited`, `Forbidden`, `Unauthorized`, `ValidationFailed` |
| `api/endpoints.py` | One function per endpoint, e.g. `get_cluster(c, project_id, cluster_id) -> tuple[dict, str | None]`, `update_cluster(c, project_id, cluster_id, body, if_match)`; docstring links the API reference section |

Retry policy: [00-architecture.md §9](00-architecture.md#9-api-client-behaviour).

## Acceptance criteria & tests

### AC1 — Authentication headers
**Given** `CAPELLA_API_KEY=k`, **then** every request carries `Authorization: Bearer k`, `Accept: application/json` and `User-Agent: capellactl/<v> (python/<v>)`. **Given** the variable is unset (and no `BEARER_TOKEN` fallback), **then** the command exits 3 before any request.

| Test | Location | Verifies |
|---|---|---|
| `test_client_ac1_headers` | `tests/contract/test_client.py` | `responses` captures headers |
| `test_client_ac1_missing_key_exit_3_no_request` | `tests/scenario/test_auth.py` | `fake.calls()` empty |
| `test_client_ac1_bearer_token_fallback_warns` | `tests/unit/api/test_auth_env.py` | Deprecation warning text |

### AC2 — 401 and 403 messages
**Given** a `401`, **then** the CLI prints `API Key Token rejected: check that CAPELLA_API_KEY …` (API Key Token vs API Key ID, IP allowlist) followed by Capella's own hint, and exits 1. **Given** a `403` on `POST …/clusters`, **then** it prints the API `message` plus `required role: Organization Owner, Project Owner or Project Manager`.

| Test | Location | Verifies |
|---|---|---|
| `test_client_ac2_401_message` | `tests/scenario/test_auth.py` | |
| `test_client_ac2_403_names_roles` | same | Role table lookup by endpoint |

### AC3 — Retries with backoff and Retry-After
**Given** a `GET` that returns `429` (with `Retry-After: 2`) then `200`, **then** the client sleeps 2 s and returns the 200. **Given** `503` six times, **then** it raises after 6 attempts with exponential, jittered, capped delays. Each retry logs `warn: retrying GET /v4/… (attempt 2/6) after 429`.

| Test | Location | Verifies |
|---|---|---|
| `test_client_ac3_retry_after_honoured` | `tests/contract/test_retries.py` | Patched sleep receives 2 |
| `test_client_ac3_gives_up_after_six` | same | |
| `test_client_ac3_backoff_capped_at_30s` | `tests/unit/api/test_backoff.py` | Seeded jitter |
| `test_client_ac3_retry_logged` | `tests/contract/test_retries.py` | `caplog` |

### AC4 — POST is never retried blindly
**Given** a `POST` that fails with a read timeout after sending, **then** the client does **not** resend and raises `AmbiguousWriteError`. **Given** a `POST` answered `429`, **then** it is retried (the request was rejected, not executed).

| Test | Location | Verifies |
|---|---|---|
| `test_client_ac4_post_read_timeout_not_retried` | `tests/contract/test_retries.py` | Exactly one POST recorded |
| `test_client_ac4_post_429_retried` | same | |

### AC5 — Pagination
**Given** 230 clusters, **then** `paginate()` requests pages 1, 2, 3 with `perPage=100`, stops when `cursor.pages.next` is absent, and returns 230 items. **Given** a response without `cursor` (endpoints that are not paginated, such as scopes), **then** the single page is returned.

| Test | Location | Verifies |
|---|---|---|
| `test_client_ac5_follows_cursor_next` | `tests/contract/test_pagination.py` | |
| `test_client_ac5_no_cursor_single_page` | same | |

### AC6 — Structured errors
**Given** a `422` body `{"httpStatusCode":422,"code":4001,"message":"…","hint":"…"}`, **then** `ValidationFailed` is raised with all four fields, and the CLI prints `Error: <message>` and `Hint: <hint>`. **Given** a non-JSON body, **then** the error shows the status and first 200 characters, redacted.

| Test | Location | Verifies |
|---|---|---|
| `test_errors_ac6_parse_error_body` | `tests/unit/api/test_errors.py` | Each status → subclass |
| `test_errors_ac6_non_json_body` | same | |
| `test_cli_ac6_prints_message_and_hint` | `tests/scenario/test_errors.py` | |

### AC7 — ETag round-trip
**Given** `get_cluster` returns `ETag: "17"`, **then** it returns `(body, "17")`; **given** `update_cluster(..., if_match="17")`, **then** the request has `If-Match: 17`; **given** a `412`, **then** `PreconditionFailed` is raised.

| Test | Location | Verifies |
|---|---|---|
| `test_endpoints_ac7_get_returns_etag` | `tests/contract/test_endpoints_cluster.py` | |
| `test_endpoints_ac7_update_sends_if_match` | same | |
| `test_endpoints_ac7_412_raises` | same | |

### AC8 — Debug logging is redacted
**Given** `--log-level debug`, **then** each request logs `METHOD path status duration_ms`; the `Authorization` header and any `password` in bodies are shown as `***`.

| Test | Location | Verifies |
|---|---|---|
| `test_client_ac8_debug_log_redacted` | `tests/contract/test_client.py` | `assert_no_secret` on `caplog.text` |

### AC9 — Endpoint coverage
**Given** `api/endpoints.py`, **then** it has a function for every endpoint listed in the story files of this release, and each contract test file covers method, path and body for its resource.

| Test | Location | Verifies |
|---|---|---|
| `test_endpoints_ac9_all_release_endpoints_present` | `tests/unit/api/test_endpoint_inventory.py` | Inventory list vs module functions |

## Out of scope
- Async I/O; the tool is sequential by design (dependency order).
- Calling endpoints not used in 1.0.0.

## Open questions
- Is a documented per-key rate limit available from Capella support, so the default backoff can be tuned?

## Implementation notes (as built)
- ETag format (2026-10-07): Capella sends `ETag: Version: N`, while `If-Match` takes the bare `N` (the spec's example is `'12'`). The client sent `Version: N` back, so every conditional `PUT` (project, cluster, schedule, collection, credential) got 412 and apply reported `changed concurrently`. `ApiResponse.etag` now strips the `Version:` prefix, and the fake Capella sends the real header format. Test: `test_endpoints_ac7_capella_version_etag_is_sent_bare` (tests/contract/test_endpoints_cluster.py).
- Pagination follows `cursor.pages.next` (found in the OpenAPI list responses); endpoints without a cursor (scopes) return one page.
- `POST` is retried only on 429 and on connect timeouts / connection-refused errors; a 5xx on `POST` is not retried.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_client_ac1_headers` (tests/contract/test_client.py)<br>`test_client_ac1_missing_key_exit_3_no_request` (tests/scenario/test_auth.py)<br>`test_client_ac1_bearer_token_fallback_warns` (tests/unit/api/test_auth_env.py) |
| AC2 | `test_client_ac2_401_message` (tests/scenario/test_auth.py)<br>`test_client_ac2_403_names_roles` (tests/scenario/test_auth.py)<br>`test_client_ac2_403_on_read_names_roles` (tests/scenario/test_auth.py) |
| AC3 | `test_client_ac3_retry_after_honoured` (tests/contract/test_retries.py)<br>`test_client_ac3_gives_up_after_six` (tests/contract/test_retries.py)<br>`test_client_ac3_retry_logged` (tests/contract/test_retries.py)<br>`test_client_ac3_backoff_capped_at_30s` (tests/unit/api/test_backoff.py) |
| AC4 | `test_client_ac4_post_read_timeout_not_retried` (tests/contract/test_retries.py)<br>`test_client_ac4_post_429_retried` (tests/contract/test_retries.py)<br>`test_client_ac4_post_connect_timeout_retried` (tests/contract/test_retries.py)<br>`test_client_ac4_post_5xx_not_retried` (tests/contract/test_retries.py) |
| AC5 | `test_client_ac5_follows_cursor_next` (tests/contract/test_pagination.py)<br>`test_client_ac5_no_cursor_single_page` (tests/contract/test_pagination.py) |
| AC6 | `test_cli_ac6_prints_message_and_hint` (tests/scenario/test_errors.py)<br>`test_errors_ac6_parse_error_body` (tests/unit/api/test_errors.py)<br>`test_errors_ac6_non_json_body` (tests/unit/api/test_errors.py) |
| AC7 | `test_endpoints_ac7_get_returns_etag` (tests/contract/test_endpoints_cluster.py)<br>`test_endpoints_ac7_update_sends_if_match` (tests/contract/test_endpoints_cluster.py)<br>`test_endpoints_ac7_412_raises` (tests/contract/test_endpoints_cluster.py) |
| AC8 | `test_client_ac8_debug_log_redacted` (tests/contract/test_client.py) |
| AC9 | `test_endpoints_ac9_all_release_endpoints_present` (tests/unit/api/test_endpoint_inventory.py) |
