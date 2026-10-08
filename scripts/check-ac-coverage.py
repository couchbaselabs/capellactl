#!/usr/bin/env python3
"""Fail when a story AC has no tagged test (CAP-001 AC5; 00-architecture.md section 12.2).

Every `### ACn` heading of an `Implemented` story must have at least one test marked
`@pytest.mark.story("CAP-NNN", "ACn")` under tests/, or the check fails. `In progress` stories are
expected to have gaps: they are listed but do not fail the check (use --strict to make them fail).

Usage: python3 scripts/check-ac-coverage.py [--docs docs/release-1.0.0] [--tests tests] [--strict] [--all]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHECKED = {"In progress", "Implemented"}
MARK_RE = re.compile(r"""story\(\s*["'](CAP-\d{3})["']\s*,\s*["'](AC\d+)["']\s*\)""")


def story_acs(docs: Path, include_all: bool) -> dict[str, tuple[str, list[str]]]:
    out: dict[str, tuple[str, list[str]]] = {}
    for f in sorted(docs.glob("CAP-*.md")):
        text = f.read_text(encoding="utf-8")
        m = re.match(r"#\s+(CAP-\d{3})", text)
        if not m:
            continue
        status = ""
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith("| Epic | Priority | Points |"):
                status = lines[i + 2].strip().strip("|").split("|")[-1].strip()
                break
        if not include_all and status not in CHECKED:
            continue
        out[m.group(1)] = (status, re.findall(r"^### (AC\d+)\b", text, flags=re.M))
    return out


def tagged(tests: Path) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for f in tests.rglob("*.py"):
        found.update(MARK_RE.findall(f.read_text(encoding="utf-8")))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="docs/release-1.0.0")
    ap.add_argument("--tests", default="tests")
    ap.add_argument("--strict", action="store_true", help="also fail on gaps in In progress stories")
    ap.add_argument("--all", action="store_true", help="check every story regardless of status")
    a = ap.parse_args(argv)
    acs = story_acs(Path(a.docs), a.all)
    have = tagged(Path(a.tests))
    failing: list[str] = []
    pending: list[str] = []
    for sid, (status, lst) in acs.items():
        for ac in lst:
            if (sid, ac) in have:
                continue
            (failing if status == "Implemented" or a.strict or a.all else pending).append(f"{sid} {ac}")
    total = sum(len(lst) for _, lst in acs.values())
    covered = total - len(failing) - len(pending)
    if pending:
        print(f"In progress: {len(pending)} acceptance criteria not tested yet:")
        for m in pending:
            print(f"  {m}")
    if failing:
        print(f"FAIL: {len(failing)} acceptance criteria of Implemented stories have no tagged test:")
        for m in failing:
            print(f"  {m}")
        return 1
    print(f"AC coverage OK: {covered}/{total} acceptance criteria in {len(acs)} stories have tagged tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
