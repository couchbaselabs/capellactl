#!/usr/bin/env python3
"""Apply or check the GitHub rulesets and repository settings that protect main and release tags (CAP-050).

    python scripts/github-rulesets.py apply      # create or update them on GitHub (needs repository admin)
    python scripts/github-rulesets.py --check    # exit 1, naming each difference, when GitHub differs from the files

The rulesets are .github/rulesets/*.json, in the API's own format, matched to the live ones by name. Calls go
through `gh api` (GH_TOKEN, or `gh auth login`; --check needs Administration: read). `apply` writes only what
differs, so a second run makes no POST, PUT or PATCH. --report-only prints the result and always exits 0 (the
release workflow's manual dry run). Neither is part of `make check`, which runs offline and without credentials.

Two rulesets per target, because a bypass skips every rule of its ruleset: `main` (pull request, CI, no
force-push or deletion; nobody bypasses) and `main-review` (the approvals; the admin role bypasses it, in pull
requests only, until a second code owner exists), and `release-tags` (no one moves or deletes a v* tag) and
`release-tags-create` (only the admin role creates one).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULESETS = ROOT / ".github" / "rulesets"
# Repository settings that go with the rulesets: squash or rebase only, merged branches deleted, and a read-only
# workflow token that may still open the release's downloads pull request (CAP-045).
SETTINGS = {"allow_merge_commit": False, "allow_squash_merge": True, "allow_rebase_merge": True,
            "delete_branch_on_merge": True}
WORKFLOW = {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": True}
COMPARED = ("target", "enforcement", "conditions", "bypass_actors", "rules")

Api = Callable[[str, str, "dict[str, Any] | None"], Any]


def gh(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    args = ["gh", "api", "-X", method, "-H", "Accept: application/vnd.github+json", path]
    if body is not None:
        args += ["--input", "-"]
    r = subprocess.run(args, input=None if body is None else json.dumps(body), capture_output=True, text=True,
                       timeout=60, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"github-rulesets: gh api {method} {path} failed: {r.stderr.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def desired() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RULESETS.glob("*.json"))]


def _diff(want: Any, have: Any, where: str) -> list[str]:
    """Where `have` differs from `want`. Keys `want` leaves out are API defaults and not compared."""
    if isinstance(want, dict):
        if not isinstance(have, dict):
            return [f"{where}: is {have!r}, want {want!r}"]
        return [d for k, v in want.items() for d in _diff(v, have.get(k), f"{where}.{k}")]
    if isinstance(want, list) and isinstance(have, list):
        def key(x: Any) -> str:
            return json.dumps(x, sort_keys=True)
        missing = [x for x in want if key(x) not in {key(y) for y in have}]
        extra = [y for y in have if key(y) not in {key(x) for x in want}]
        return ([f"{where}: missing {key(x)}" for x in missing] + [f"{where}: unexpected {key(y)}" for y in extra])
    return [] if want == have else [f"{where}: is {have!r}, want {want!r}"]


def ruleset_diff(want: dict[str, Any], have: dict[str, Any]) -> list[str]:
    name = want["name"]
    out = [d for k in COMPARED if k != "rules" for d in _diff(want.get(k), have.get(k), f"{name}.{k}")]
    want_rules = {r["type"]: r.get("parameters", {}) for r in want["rules"]}
    have_rules = {r["type"]: r.get("parameters", {}) for r in have.get("rules") or []}
    out += [f"{name}: rule {t} removed" for t in want_rules if t not in have_rules]
    out += [f"{name}: rule {t} added" for t in have_rules if t not in want_rules]
    out += [d for t in want_rules if t in have_rules for d in _diff(want_rules[t], have_rules[t], f"{name}.{t}")]
    return out


def run(repo: str, api: Api, write: bool) -> list[str]:
    """Differences between GitHub and the files; with write, fix each one. Returns what was (or would be) changed."""
    base = f"repos/{repo}"
    live = {r["name"]: r for r in api("GET", f"{base}/rulesets?includes_parents=false&per_page=100", None) or []}
    lines: list[str] = []
    for want in desired():
        name = want["name"]
        if name not in live:
            lines.append(f"{name}: ruleset missing")
            if write:
                api("POST", f"{base}/rulesets", want)
            continue
        diffs = ruleset_diff(want, api("GET", f"{base}/rulesets/{live[name]['id']}", None))
        lines += diffs
        if diffs and write:
            api("PUT", f"{base}/rulesets/{live[name]['id']}", want)
    names = {w["name"] for w in desired()}
    lines += [f"{n}: ruleset not in .github/rulesets" for n in live if n not in names]
    for path, want_settings, method in ((base, SETTINGS, "PATCH"), (f"{base}/actions/permissions/workflow", WORKFLOW, "PUT")):
        diffs = _diff(want_settings, api("GET", path, None), "settings" if path == base else "workflow token")
        lines += diffs
        if diffs and write:
            api(method, path, want_settings)
    return lines


def main(argv: list[str] | None = None, api: Api = gh) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", nargs="?", choices=["apply"])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "couchbaselabs/capellactl"))
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args(argv)
    if (a.action == "apply") == a.check:
        ap.error("give exactly one of: apply, --check")
    lines = run(a.repo, api, write=a.action == "apply")
    for line in lines:
        print(f"  {line}")
    if a.action == "apply":
        print(f"github-rulesets: {len(lines)} change(s) applied to {a.repo}" if lines
              else f"github-rulesets: {a.repo} already matches .github/rulesets; nothing changed")
        return 0
    if not lines:
        print(f"github-rulesets: {a.repo} matches .github/rulesets")
        return 0
    print(f"github-rulesets: {a.repo} differs from .github/rulesets in {len(lines)} place(s); "
          "run: python scripts/github-rulesets.py apply" + (" (report only: not blocking this run)" if a.report_only else ""))
    return 0 if a.report_only else 1


if __name__ == "__main__":
    sys.exit(main())
