"""CAP-001 AC4: exit codes defined once, never as literals."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from capellactl.cli.exit_codes import ExitCode

PKG = Path(__file__).resolve().parents[3] / "capellactl"


@pytest.mark.story("CAP-001", "AC4")
def test_exit_codes_ac4_values():
    assert {int(c) for c in ExitCode} == {0, 1, 2, 3, 4, 5, 130}


@pytest.mark.story("CAP-001", "AC4")
def test_exit_codes_ac4_no_numeric_literals():
    pattern = re.compile(r"\b(sys\.exit|ctx\.exit|\.exit)\(\s*\d+\s*\)")
    offenders = [f"{p.relative_to(PKG)}:{i}" for p in PKG.rglob("*.py")
                 for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if pattern.search(line)]
    assert offenders == []
