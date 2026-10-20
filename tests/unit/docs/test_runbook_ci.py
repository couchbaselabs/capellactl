"""CAP-042 AC8: the runbook shows CI/CD use."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RUNBOOK = Path(__file__).resolve().parents[3] / "docs" / "runbook.md"


@pytest.mark.story("CAP-042", "AC8")
def test_ci_ac8_runbook_ci_section():
    text = RUNBOOK.read_text(encoding="utf-8")
    intro = text.split("\n# Part 1", 1)[0]
    assert "-y" in intro and "--quiet" in intro and "capellactl help ci" in intro
    section = re.search(r"^## CI/CD\n(.*?)(?=^## )", text, flags=re.S | re.M)
    assert section, "no CI/CD section in the command reference"
    for s in ("capellactl -y -q apply", "CAPELLACTL_QUIET=true", "plan --detailed-exitcode", "capellactl help ci",
              "no environment variable for approval"):
        assert s in section.group(1), s
    # its commands are parsed with every other documented command by test_docs_ac2_commands_parse
