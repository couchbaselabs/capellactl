"""Secret redaction for every output channel (CAP-008).

All secret values that pass through the tool (API key, resolved passwords, passwords returned by
Capella) are registered here. Every renderer, the logging filter and the top-level exception handler
pass text through `redact()` before it leaves the process.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from typing import Any

MASK = "***"
SECRET_KEYS = {"password", "authorization", "apikey", "api_key", "secret", "token"}


class Redactor:
    def __init__(self) -> None:
        self._values: set[str] = set()
        self._lock = threading.Lock()

    def register(self, value: str | None) -> None:
        # Very short values would mask ordinary words; Capella secrets are at least 8 characters.
        if value and len(value) >= 4:
            with self._lock:
                self._values.add(value)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    @property
    def values(self) -> Iterable[str]:
        return tuple(self._values)

    def redact(self, text: Any) -> str:
        s = text if isinstance(text, str) else str(text)
        # Longest first so a secret containing another secret is fully masked.
        for v in sorted(self._values, key=len, reverse=True):
            if v in s:
                s = s.replace(v, MASK)
        return s

    def redact_obj(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: (MASK if isinstance(k, str) and k.lower() in SECRET_KEYS and v not in (None, "") else self.redact_obj(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [self.redact_obj(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self.redact_obj(v) for v in obj)
        if isinstance(obj, str):
            return self.redact(obj)
        return obj


redactor = Redactor()


def redact(text: Any) -> str:
    return redactor.redact(text)


def redact_obj(obj: Any) -> Any:
    return redactor.redact_obj(obj)


class RedactingFilter(logging.Filter):
    """Logging filter: masks registered secrets in the final formatted message."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging break the command
            msg = str(record.msg)
        record.msg = redactor.redact(msg)
        record.args = None
        if record.exc_text:
            record.exc_text = redactor.redact(record.exc_text)
        return True
