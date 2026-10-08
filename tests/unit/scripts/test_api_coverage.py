"""The API coverage reports are generated from the story statuses and must never be stale."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "update-api-coverage.py"


def test_api_coverage_reports_up_to_date():
    r = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr + r.stdout


def test_api_coverage_database_credentials_done():
    text = (ROOT / "docs" / "release-1.0.0" / "API-COVERAGE.md").read_text(encoding="utf-8")
    assert "### Database credentials — 5 ops (5 ✅)" in text
    for verb in ("list", "get", "create", "update", "delete"):
        assert f"| `capellactl credential {verb}` | ✅ Done |" in text
