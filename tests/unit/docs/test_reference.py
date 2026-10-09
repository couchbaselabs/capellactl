"""CAP-033 AC3: docs/reference.md is generated from the config schema and current."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.story("CAP-033", "AC3")
def test_docs_ac3_reference_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "update-reference.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    text = (ROOT / "docs" / "reference.md").read_text()
    for field in ("`deletionProtection`", "`node.compute.cpu`", "`hibernation.weekdays`", "`memoryAllocationInMb`",
                  "**immutable**", "deletionProtection (Update Deletion Protection)"):
        assert field in text, field
    make = (ROOT / "Makefile").read_text()
    assert "docs:" in make and "docs-check" in make.split("check:")[-1]
