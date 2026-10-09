"""CAP-033 AC1: every example capella.yaml validates."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[3] / "docs" / "release-1.0.0" / "examples"
DUMMY_ENV = {"ORDERS_APP_PASSWORD": "Orders!Passw0rd-2026", "REPORTING_RO_PASSWORD": "Rep0rting!pw-2026"}


@pytest.mark.story("CAP-033", "AC1")
@pytest.mark.parametrize("example", sorted(p.name for p in EXAMPLES.glob("*.yaml")))
def test_docs_ac1_examples_validate(run, tmp_path, example):
    shutil.copy(EXAMPLES / example, tmp_path / example)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "reporting_ro.txt").write_text("Rep0rting!pw-2026\n")  # ${file:./secrets/…} references
    r = run("-c", str(tmp_path / example), "validate", extra_env=DUMMY_ENV)
    assert r.exit_code == 0, r.output
    assert "Configuration valid" in r.output


def test_docs_ac1_story_examples_present():
    names = {p.name for p in EXAMPLES.glob("*.yaml")}
    assert {"capella.yaml", "single-node-dev.yaml", "gcp-prod.yaml", "azure-prod.yaml"} <= names
