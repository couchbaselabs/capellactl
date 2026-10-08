"""CAP-001 AC5: the AC coverage check."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("check_ac", ROOT / "scripts" / "check-ac-coverage.py")
assert spec and spec.loader
check_ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_ac)

STORY = """# CAP-999 — Fixture story

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P0 | 1 | — | In progress |

### AC1 — One
### AC2 — Two
### AC3 — Three
"""


def _setup(tmp_path: Path, tagged: list[str]) -> tuple[Path, Path]:
    docs, tests = tmp_path / "docs", tmp_path / "tests"
    docs.mkdir()
    tests.mkdir()
    (docs / "CAP-999-fixture.md").write_text(STORY)
    body = "\n".join(f'@pytest.mark.story("CAP-999", "{ac}")\ndef test_x_{ac.lower()}(): ...' for ac in tagged)
    (tests / "test_fixture.py").write_text("import pytest\n" + body)
    return docs, tests


def _status(docs, status):
    p = docs / "CAP-999-fixture.md"
    p.write_text(p.read_text().replace("In progress", status))


@pytest.mark.story("CAP-001", "AC5")
def test_ac_coverage_ac5_detects_missing_test(tmp_path, capsys):
    docs, tests = _setup(tmp_path, ["AC1", "AC2"])
    _status(docs, "Implemented")
    assert check_ac.main(["--docs", str(docs), "--tests", str(tests)]) == 1
    assert "CAP-999 AC3" in capsys.readouterr().out


@pytest.mark.story("CAP-001", "AC5")
def test_ac_coverage_ac5_in_progress_gaps_listed_not_failed(tmp_path, capsys):
    docs, tests = _setup(tmp_path, ["AC1"])
    assert check_ac.main(["--docs", str(docs), "--tests", str(tests)]) == 0
    out = capsys.readouterr().out
    assert "In progress: 2 acceptance criteria not tested yet" in out and "CAP-999 AC3" in out
    assert check_ac.main(["--docs", str(docs), "--tests", str(tests), "--strict"]) == 1


@pytest.mark.story("CAP-001", "AC5")
def test_ac_coverage_ac5_passes_when_all_tagged(tmp_path, capsys):
    docs, tests = _setup(tmp_path, ["AC1", "AC2", "AC3"])
    assert check_ac.main(["--docs", str(docs), "--tests", str(tests)]) == 0


@pytest.mark.story("CAP-001", "AC5")
def test_ac_coverage_ac5_ignores_not_started(tmp_path):
    docs, tests = _setup(tmp_path, [])
    _status(docs, "Not started")
    assert check_ac.main(["--docs", str(docs), "--tests", str(tests)]) == 0
