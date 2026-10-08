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
