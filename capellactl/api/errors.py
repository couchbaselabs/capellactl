"""Structured Management API errors (CAP-003 AC6).

Capella error body (OpenAPI schema `Error`): {httpStatusCode, code, message, hint}.
"""

from __future__ import annotations

import json
from typing import Any

from capellactl.output.redact import redact


class CapellaApiError(Exception):
    def __init__(
        self,
        http_status: int,
        message: str,
        code: int | None = None,
        hint: str | None = None,
        method: str = "",
        path: str = "",
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.message = message
        self.hint = hint
        self.method = method
        self.path = path

    def __str__(self) -> str:
        return redact(f"{self.method} {self.path}: {self.http_status} {self.message}".strip())


class Unauthorized(CapellaApiError):
    pass


class Forbidden(CapellaApiError):
    pass


class NotFound(CapellaApiError):
    pass


class Conflict(CapellaApiError):
    pass


class PreconditionFailed(CapellaApiError):
    pass


class ValidationFailed(CapellaApiError):
    pass


class RateLimited(CapellaApiError):
    pass


class ServerError(CapellaApiError):
    pass


class AmbiguousWriteError(Exception):
    """A POST may or may not have been executed (for example a read timeout after sending).

    The caller must re-observe by natural key before deciding whether to retry (CAP-003 AC4).
    """

    def __init__(self, method: str, path: str, cause: BaseException) -> None:
        super().__init__(f"{method} {path}: no response ({type(cause).__name__}); the request may have been applied")
        self.method = method
        self.path = path
        self.cause = cause


class TransportError(Exception):
    """The API could not be reached after all retries."""


_BY_STATUS: dict[int, type[CapellaApiError]] = {
    401: Unauthorized,
    403: Forbidden,
    404: NotFound,
    409: Conflict,
    412: PreconditionFailed,
    422: ValidationFailed,
    400: ValidationFailed,
    429: RateLimited,
}


def error_from_response(status: int, body_text: str, method: str, path: str) -> CapellaApiError:
    cls = _BY_STATUS.get(status, ServerError if status >= 500 else CapellaApiError)
    message: str
    code: int | None = None
    hint: str | None = None
    try:
        body: Any = json.loads(body_text) if body_text else {}
    except ValueError:
        body = None
    if isinstance(body, dict) and ("message" in body or "code" in body):
        message = str(body.get("message") or f"HTTP {status}")
        raw_code = body.get("code")
        code = int(raw_code) if isinstance(raw_code, (int, str)) and str(raw_code).isdigit() else None
        hint = body.get("hint") or None
    else:
        snippet = (body_text or "").strip().replace("\n", " ")[:200]
        message = f"HTTP {status}" + (f": {snippet}" if snippet else "")
    return cls(status, redact(message), code=code, hint=redact(hint) if hint else None, method=method, path=path)
