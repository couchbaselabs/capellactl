"""A warning and what to do about it (CAP-063), for code outside cli/ that collects warnings to print later."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Notice:
    what: str
    action: str

    def __str__(self) -> str:
        return f"{self.what}. {self.action}"
