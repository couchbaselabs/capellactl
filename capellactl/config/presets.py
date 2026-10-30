"""Cluster size presets, read from presets.yaml so sizes change without code changes (CAP-035 AC3)."""

from __future__ import annotations

from functools import cache
from importlib import resources
from typing import Any

import yaml


@cache
def load_presets() -> dict[str, dict[str, Any]]:
    text = resources.files("capellactl.config").joinpath("presets.yaml").read_text(encoding="utf-8")
    return dict(yaml.safe_load(text))


def is_single_node(preset: dict[str, Any]) -> bool:
    return preset.get("configurationType") == "singleNode"


@cache
def load_compute_sizes() -> dict[str, dict[str, list[tuple[int, int]]]]:
    """Known node sizes per provider from compute.yaml (CAP-051 AC9): {provider: {sizes, singleNode: [(cpu, ram)]}}."""
    text = resources.files("capellactl.config").joinpath("compute.yaml").read_text(encoding="utf-8")
    out: dict[str, dict[str, list[tuple[int, int]]]] = {}
    for provider, kinds in (yaml.safe_load(text) or {}).items():
        out[provider] = {k: [tuple(int(x) for x in str(s).split("/")) for s in v]  # type: ignore[misc]
                         for k, v in (kinds or {}).items()}
    return out


def known_size(provider: str, cpu: int, ram: int, single: bool) -> bool:
    """True when Capella's documentation lists cpu/ram for this provider (single-node sizes only when single)."""
    kinds = load_compute_sizes().get(provider)
    if kinds is None:
        return True
    return (cpu, ram) in kinds.get("sizes", []) or (single and (cpu, ram) in kinds.get("singleNode", []))


@cache
def load_disk_types() -> dict[str, dict[str, dict[str, Any]]]:
    """Disk types per provider and what each means, from disks.yaml (CAP-060): {provider: {type: facts}}."""
    text = resources.files("capellactl.config").joinpath("disks.yaml").read_text(encoding="utf-8")
    return {str(p): {str(t): dict(v) for t, v in (types or {}).items()} for p, types in (yaml.safe_load(text) or {}).items()}


def _step(table: list[list[int]], size: int) -> int | None:
    """The value of the last [from, value] step at or below `size` (None below the first step)."""
    found = None
    for start, value in table:
        if size >= start:
            found = value
    return found


def disk_facts(provider: str, disk_type: str) -> dict[str, Any] | None:
    return load_disk_types().get(provider, {}).get(disk_type)


def default_iops(provider: str, disk_type: str, size: int | None) -> int | None:
    """Capella's recommended IOPS for a disk of this size (gp3, io2, Ultra); None when the type sets or derives it."""
    facts = disk_facts(provider, disk_type)
    if not facts or not facts.get("defaults"):
        return None
    lowest = facts["defaults"][0]
    return _step(facts["defaults"], size if size is not None else lowest[0]) or lowest[1]


def iops_range(provider: str, disk_type: str, size: int | None) -> tuple[int, int] | None:
    """(min, max) IOPS a disk of this type and size takes; None when IOPS cannot be set."""
    facts = disk_facts(provider, disk_type)
    if not facts or "iops" not in facts:
        return None
    lo, hi = facts["iops"]
    cap = _step(facts.get("iopsCap") or [], size) if size is not None else None
    return int(lo), int(min(hi, cap) if cap else hi)


def disk_size_text(facts: dict[str, Any]) -> str:
    if "fixedSize" in facts:
        return str(facts["fixedSize"])
    if "sizes" in facts:
        s = facts["sizes"]
        return f"{s[0]}, {s[1]}, … {s[-1]}"
    size = facts["size"]
    return f"{size[0]}–{size[1]}" if len(size) > 1 else f"{size[0]} and up"


def disk_iops_text(facts: dict[str, Any]) -> str:
    if "fixedIops" in facts:
        return str(facts["fixedIops"])
    if "perGb" in facts:
        return f"{facts['perGb']} per GB"
    lo, hi = facts["iops"]
    return f"{lo}–{hi}"
