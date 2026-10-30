"""The API coverage reports are generated from the story statuses and must never be stale."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "update-api-coverage.py"


def test_api_coverage_reports_up_to_date():
    r = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, cwd=ROOT, encoding="utf-8")
    assert r.returncode == 0, r.stderr + r.stdout


def test_api_coverage_database_credentials_done():
    text = (ROOT / "docs" / "release-1.0.0" / "API-COVERAGE.md").read_text(encoding="utf-8")
    assert "### Database credentials — 5 ops (5 ✅)" in text
    for verb in ("list", "get", "create", "update", "delete"):
        assert f"| `capellactl credential {verb}` | ✅ Done |" in text


def test_api_coverage_release_15_plans_every_operation_left_out_of_10():
    db = (ROOT / "docs" / "release-1.0.0" / "API-COVERAGE.md").read_text(encoding="utf-8")
    r15 = (ROOT / "docs" / "release-1.5.0" / "API-COVERAGE.md").read_text(encoding="utf-8")
    later = int(re.search(r"\| All operational-database operations \| \d+ \| \d+ \| \d+ \| \d+ \| \d+ \| (\d+) \|", db)[1])
    planned = int(re.search(r"\| \*\*API operations planned for 1\.5\.0\*\* \| \*\*(\d+)\*\*", r15)[1])
    assert later == planned
    assert "| `capellactl db-role create` |" in r15
    assert "](../release-1.5.0/CAP-064-custom-database-roles.md)" in db


def test_api_coverage_breakdown_adds_up_on_every_report():
    tables = []
    for rel in ("release-1.0.0/API-COVERAGE.md", "release-1.5.0/API-COVERAGE.md",
                "release-2.0.0/API-COVERAGE-APP-SERVICES.md"):
        text = (ROOT / "docs" / rel).read_text(encoding="utf-8")
        table = text[text.index("**Where the spec's operations go**"):text.index("| **Total in the spec** |")]
        counts = [int(m) for m in re.findall(r"^\| [^|*][^|]* \| (\d+) \|", table, flags=re.M)]
        total = int(re.search(r"\| \*\*Total in the spec\*\* \| \*\*(\d+)\*\*", text)[1])
        assert sum(counts) == total
        tables.append(table)
    assert tables[0] == tables[1] == tables[2]
