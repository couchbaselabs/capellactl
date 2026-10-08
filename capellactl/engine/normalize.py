"""Comparison rules (docs/release-1.0.0/00-architecture.md section 6.3).

A naive comparison reports differences that are not real and breaks idempotency. Everything here
turns desired and observed values into a canonical form before they are compared.
"""

from __future__ import annotations

from typing import Any

from capellactl.resources.base import Change

PRIVILEGE_ALIASES = {"read": "data_reader", "write": "data_writer"}
CASE_INSENSITIVE_PATHS = {"support.plan"}
IGNORED_FIELDS = {"id", "audit", "stats", "connectionString", "currentState", "expressScaling", "appServiceId", "etag"}


def group_key(group: dict[str, Any]) -> str:
    """A service group is identified by its sorted services set, e.g. 'data,index,query'."""
    return ",".join(sorted(group.get("services") or []))


def canon_privileges(privs: list[str]) -> list[str]:
    return sorted({PRIVILEGE_ALIASES.get(p, p) for p in privs})


def canon_flush(body: dict[str, Any]) -> bool | None:
    """flushEnabled replaces the deprecated flush; read flush only when flushEnabled is absent."""
    if "flushEnabled" in body:
        return bool(body["flushEnabled"])
    if "flush" in body:
        return bool(body["flush"])
    return None


def canon_value(path: str, value: Any) -> Any:
    if path in CASE_INSENSITIVE_PATHS and isinstance(value, str):
        return value.lower()
    if path.endswith("services") and isinstance(value, list):
        return sorted(value)
    if path.endswith("privileges") and isinstance(value, list):
        return canon_privileges(value)
    return value


def field_changes(desired: Any, observed: Any, prefix: str = "", skip: set[str] | None = None) -> list[Change]:
    """Changes for fields present in `desired` only (fields the user omitted are never compared)."""
    skip = skip or set()
    changes: list[Change] = []
    if isinstance(desired, dict):
        obs = observed if isinstance(observed, dict) else {}
        for k, v in desired.items():
            if k in skip or k in IGNORED_FIELDS:
                continue
            path = f"{prefix}.{k}" if prefix else k
            changes += field_changes(v, obs.get(k), path, skip=None)
        return changes
    d, o = canon_value(prefix, desired), canon_value(prefix, observed)
    if d != o:
        changes.append(Change(prefix, observed, desired))
    return changes


def deep_merge(base: Any, overlay: Any) -> Any:
    """Observed overlaid with desired (section 6.4): unset fields keep their current values."""
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for k, v in overlay.items():
            out[k] = deep_merge(base.get(k), v) if k in base else v
        return out
    return overlay if overlay is not None else base
