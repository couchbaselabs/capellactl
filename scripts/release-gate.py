#!/usr/bin/env python3
"""Block a release unless the nightly integration suite was green three nights running (CAP-032 AC5).

Usage: python scripts/release-gate.py --commit SHA [--repo OWNER/NAME] [--branch main] [--workflow nightly.yml]
                                      [--nights 3] [--runs-json FILE] [--report-only]

The rule: the last N scheduled runs of the nightly workflow on the branch all succeeded, ran on N consecutive
nights (UTC dates), and the newest of them tested exactly the commit being released. So: tag the commit the last
green nightly ran on. Runs are read with `gh api` (GH_TOKEN needs actions:read), or from --runs-json (the API's
JSON) for testing. --report-only prints the verdict and always exits 0 (the release workflow's manual dry run).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


def _day(run: dict[str, Any]) -> date:
    return datetime.fromisoformat(str(run.get("run_started_at") or run["created_at"]).replace("Z", "+00:00")).date()


def evaluate(runs: list[dict[str, Any]], commit: str, nights: int = 3) -> tuple[bool, list[str]]:
    """(passed, explanation lines) for the API's workflow runs, newest or oldest first."""
    done = [r for r in runs if r.get("status") == "completed" and r.get("event") == "schedule"]
    done.sort(key=lambda r: str(r.get("run_started_at") or r["created_at"]), reverse=True)
    last = done[:nights]
    lines = [f"{_day(r)}  {r.get('conclusion')}  {str(r.get('head_sha'))[:12]}  {r.get('html_url', '')}" for r in last]
    if len(last) < nights:
        return False, lines + [f"only {len(last)} completed nightly run(s); {nights} green nights are needed"]
    red = [r for r in last if r.get("conclusion") != "success"]
    if red:
        return False, lines + [f"{len(red)} of the last {nights} nightly runs did not succeed"]
    days = [_day(r) for r in last]
    if any(days[i] - days[i + 1] != timedelta(days=1) for i in range(len(days) - 1)):
        return False, lines + [f"the last {nights} green runs are not on consecutive nights"]
    newest = str(last[0].get("head_sha"))
    if newest != commit:
        return False, lines + [f"the newest green nightly tested {newest[:12]}, not the release commit {commit[:12]}; "
                               "tag the commit the nightly tested, or wait for the next nightly"]
    return True, lines + [f"{nights} consecutive green nights, the newest on {commit[:12]}"]


def fetch_runs(repo: str, workflow: str, branch: str) -> list[dict[str, Any]]:
    path = f"repos/{repo}/actions/workflows/{workflow}/runs?branch={branch}&event=schedule&per_page=30"
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"release-gate: gh api failed: {r.stderr.strip()}")
    return list(json.loads(r.stdout).get("workflow_runs") or [])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--commit", required=True)
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "couchbaselabs/capellactl"))
    ap.add_argument("--branch", default="main")
    ap.add_argument("--workflow", default="nightly.yml")
    ap.add_argument("--nights", type=int, default=3)
    ap.add_argument("--runs-json", type=Path)
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args(argv)
    if a.runs_json:
        runs = list(json.loads(a.runs_json.read_text(encoding="utf-8")).get("workflow_runs") or [])
    else:
        runs = fetch_runs(a.repo, a.workflow, a.branch)
    ok, lines = evaluate(runs, a.commit, a.nights)
    print(f"release gate (CAP-032): last {a.nights} nightly runs of {a.workflow} on {a.branch}")
    for line in lines:
        print(f"  {line}")
    if ok:
        print("PASSED")
        return 0
    print("FAILED" + (" (report only: not blocking this run)" if a.report_only else ""))
    return 0 if a.report_only else 1


if __name__ == "__main__":
    sys.exit(main())
