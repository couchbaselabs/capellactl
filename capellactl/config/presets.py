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
