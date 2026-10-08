"""HTTP client for the Capella Management API v4.0 (CAP-003).

Behaviour (docs/release-1.0.0/00-architecture.md section 9):
- Bearer auth, JSON, a capellactl User-Agent.
- Retries 429/500/502/503/504 and connection errors with exponential backoff and full jitter
  (1 s base, 30 s cap, 6 attempts), honouring Retry-After.
- POST is never retried blindly: only on 429 or a connection error raised before the request was sent.
  Anything ambiguous raises AmbiguousWriteError so the caller can re-observe first.
- Pagination follows cursor.pages.next.
"""

from __future__ import annotations

import logging
import platform
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from capellactl import DEFAULT_BASE_URL, __version__
from capellactl.api.errors import AmbiguousWriteError, TransportError, error_from_response
from capellactl.engine.clock import Clock, get_clock
from capellactl.output.redact import redact_obj, redactor

log = logging.getLogger("capellactl.api")

RETRY_STATUSES = {429, 500, 502, 503, 504}
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 60.0
PER_PAGE = 100


@dataclass
class ApiResponse:
    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def etag(self) -> str | None:
        raw = self.headers.get("ETag") or self.headers.get("Etag") or self.headers.get("etag")
        if raw is None:
            return None
        tag = raw.strip().strip('"')
        # Capella sends "Version: 12" but If-Match takes the bare version ("12", per the API spec).
        m = re.fullmatch(r"(?i)version:\s*(\S+)", tag)
        return m.group(1) if m else tag


def user_agent() -> str:
    return f"capellactl/{__version__} (python/{platform.python_version()})"


def backoff_delay(attempt: int, rng: random.Random, base: float = 1.0, cap: float = 30.0) -> float:
    """Full-jitter exponential backoff for retry `attempt` (1-based)."""
    ceiling = min(cap, base * (2 ** (attempt - 1)))
    return rng.uniform(0, ceiling)


def _retry_after_seconds(headers: Any) -> float | None:
    value = headers.get("Retry-After") if headers is not None else None
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _request_was_sent(exc: requests.RequestException) -> bool:
    """True when the request may have reached the server (so a POST must not be resent)."""
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return False
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return True
    text = repr(exc)
    return not ("NewConnectionError" in text or "NameResolutionError" in text or "Failed to establish" in text)


class CapellaClient:
    def __init__(
        self,
        api_key: str,
        org_id: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        session: requests.Session | None = None,
        clock: Clock | None = None,
        max_attempts: int = 6,
        rng: random.Random | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        redactor.register(api_key)
        self.api_key = api_key
        self.org_id = org_id
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.clock = clock or get_clock()
        self.max_attempts = max_attempts
        self.rng = rng or random.Random()
        self.writes_accepted = 0  # successful POST/PUT/DELETE: lets callers tell whether Capella changed

    # ------------------------------------------------------------------ paths
    @property
    def org_path(self) -> str:
        if not self.org_id:
            raise ValueError("organization ID is not set (CAPELLA_ORG_ID, profile, or organizationId in the config)")
        return f"/v4/organizations/{self.org_id}"

    # ---------------------------------------------------------------- request
    def _headers(self, has_body: bool, if_match: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": user_agent(),
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        if if_match is not None:
            headers["If-Match"] = if_match
        return headers

    def request(
        self,
        method: str,
        path: str,
        json: Any = None,
        params: dict[str, Any] | None = None,
        if_match: str | None = None,
    ) -> ApiResponse:
        method = method.upper()
        url = f"{self.base_url}{path}"
        headers = self._headers(json is not None, if_match)
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            started = time.perf_counter()
            try:
                resp = self.session.request(
                    method, url, json=json, params=params, headers=headers, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
                )
            except requests.RequestException as exc:
                last_exc = exc
                if method == "POST" and _request_was_sent(exc):
                    raise AmbiguousWriteError(method, path, exc) from exc
                if attempt < self.max_attempts:
                    delay = backoff_delay(attempt, self.rng)
                    log.warning("retrying %s %s (attempt %d/%d) after %s", method, path, attempt + 1,
                                self.max_attempts, type(exc).__name__)
                    self.clock.sleep(delay)
                    continue
                raise TransportError(f"{method} {path}: could not reach Capella ({type(exc).__name__})") from exc

            elapsed_ms = (time.perf_counter() - started) * 1000
            log.debug("%s %s %d %.0fms", method, path, resp.status_code, elapsed_ms)
            if json is not None and log.isEnabledFor(logging.DEBUG):
                log.debug("request body: %s", redact_obj(json))

            retryable = resp.status_code in RETRY_STATUSES and (method != "POST" or resp.status_code == 429)
            if retryable and attempt < self.max_attempts:
                retry_after = _retry_after_seconds(resp.headers)
                delay = retry_after if retry_after is not None else backoff_delay(attempt, self.rng)
                log.warning("retrying %s %s (attempt %d/%d) after %d", method, path, attempt + 1,
                            self.max_attempts, resp.status_code)
                self.clock.sleep(delay)
                continue
            if resp.status_code >= 400:
                raise error_from_response(resp.status_code, resp.text, method, path)
            body: Any = None
            if resp.content:
                try:
                    body = resp.json()
                except ValueError:
                    body = resp.text
            if method != "GET":
                self.writes_accepted += 1
            return ApiResponse(resp.status_code, body, dict(resp.headers))
        raise TransportError(f"{method} {path}: giving up after {self.max_attempts} attempts") from last_exc

    def get(self, path: str, params: dict[str, Any] | None = None) -> ApiResponse:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any = None) -> ApiResponse:
        return self.request("POST", path, json=json if json is not None else {})

    def put(self, path: str, json: Any = None, if_match: str | None = None) -> ApiResponse:
        return self.request("PUT", path, json=json if json is not None else {}, if_match=if_match)

    def delete(self, path: str, params: dict[str, Any] | None = None) -> ApiResponse:
        return self.request("DELETE", path, params=params)

    def paginate(self, path: str, key: str = "data", params: dict[str, Any] | None = None) -> list[Any]:
        """Return all items, following cursor.pages.next (CAP-003 AC5)."""
        items: list[Any] = []
        page: int | None = 1
        while page is not None:
            query = dict(params or {})
            query.update({"page": page, "perPage": PER_PAGE})
            body = self.get(path, params=query).body or {}
            if isinstance(body, list):
                return body
            items.extend(body.get(key) or [])
            cursor = body.get("cursor") if isinstance(body, dict) else None
            if not cursor:
                break
            nxt = (cursor.get("pages") or {}).get("next")
            page = int(nxt) if nxt else None
        return items
