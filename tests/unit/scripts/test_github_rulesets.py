"""CAP-050: rulesets protecting main and release tags, kept in .github/rulesets and applied with gh api."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.integration.harness import load_script

rs = load_script("github-rulesets")
ROOT = Path(__file__).resolve().parents[3]
ADMIN = {"actor_id": 5, "actor_type": "RepositoryRole"}


def _ruleset(name: str) -> dict[str, Any]:
    return json.loads((ROOT / ".github" / "rulesets" / f"{name}.json").read_text(encoding="utf-8"))


def _rules(name: str) -> dict[str, dict[str, Any]]:
    return {r["type"]: r.get("parameters", {}) for r in _ruleset(name)["rules"]}


class FakeGitHub:
    """The rulesets and settings endpoints as GitHub answers them: lists without rules, extra fields, defaults."""

    def __init__(self) -> None:
        self.rulesets: dict[int, dict[str, Any]] = {}
        self.settings = {"allow_merge_commit": True, "allow_squash_merge": True, "allow_rebase_merge": True,
                         "delete_branch_on_merge": False, "name": "capellactl"}
        self.workflow = {"default_workflow_permissions": "write", "can_approve_pull_request_reviews": False}
        self.calls: list[tuple[str, str]] = []

    @staticmethod
    def _stored(body: dict[str, Any], rid: int) -> dict[str, Any]:
        out = {**copy.deepcopy(body), "id": rid, "source_type": "Repository", "current_user_can_bypass": "never"}
        for r in out["rules"]:
            if r["type"] == "pull_request":
                r["parameters"] = {"required_reviewers": [], "automatic_copilot_code_review_enabled": False,
                                   **r["parameters"]}
        return out

    def __call__(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        self.calls.append((method, path))
        path = path.split("?")[0].removeprefix("repos/o/r")
        if path == "/rulesets":
            if method == "POST":
                rid = len(self.rulesets) + 1
                self.rulesets[rid] = self._stored(body or {}, rid)
                return self.rulesets[rid]
            return [{"id": i, "name": r["name"], "target": r["target"]} for i, r in self.rulesets.items()]
        if m := re.fullmatch(r"/rulesets/(\d+)", path):
            rid = int(m[1])
            if method == "PUT":
                self.rulesets[rid] = self._stored(body or {}, rid)
            return copy.deepcopy(self.rulesets[rid])
        target = self.settings if path == "" else self.workflow
        if method in ("PATCH", "PUT"):
            target.update(body or {})
        return dict(target)

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] != "GET"]


@pytest.mark.story("CAP-050", "AC1")
def test_rulesets_ac1_main_blocks_push_force_and_delete():
    main = _ruleset("main")
    assert main["target"] == "branch" and main["enforcement"] == "active"
    assert main["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert {"pull_request", "non_fast_forward", "deletion", "required_linear_history"} <= set(_rules("main"))
    assert main["bypass_actors"] == []  # nobody, admins included, pushes past CI or straight to main
    # the maintainer's decision (2026-10-20): bypass the approvals only, in pull requests, as the admin role
    review = _ruleset("main-review")
    assert review["conditions"] == main["conditions"]
    assert review["bypass_actors"] == [{**ADMIN, "bypass_mode": "pull_request"}]
    assert set(_rules("main-review")) == {"pull_request"}  # so the bypass skips no other rule


@pytest.mark.story("CAP-050", "AC2")
def test_rulesets_ac2_review_rules():
    review = _rules("main-review")["pull_request"]
    assert review["required_approving_review_count"] >= 1
    assert review["require_code_owner_review"] and review["dismiss_stale_reviews_on_push"]
    assert review["require_last_push_approval"] and review["required_review_thread_resolution"]
    assert set(review["allowed_merge_methods"]) == {"squash", "rebase"}
    pr = _rules("main")["pull_request"]  # no bypass: a pull request, resolved threads, no merge commits
    assert pr["required_review_thread_resolution"] and set(pr["allowed_merge_methods"]) == {"squash", "rebase"}
    checks = _rules("main")["required_status_checks"]
    assert checks["strict_required_status_checks_policy"] is True  # up to date with main before merging
    assert all(c["integration_id"] == 15368 for c in checks["required_status_checks"])  # set by GitHub Actions only
    assert rs.SETTINGS["allow_merge_commit"] is False and rs.SETTINGS["delete_branch_on_merge"] is True


@pytest.mark.story("CAP-050", "AC2")
def test_rulesets_ac2_required_checks_match_ci_matrix():
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    matrix = ci["jobs"]["test"]["strategy"]["matrix"]
    jobs = {f"test ({o}, {p})" for o in matrix["os"] for p in matrix["python"]}
    required = {c["context"] for c in _rules("main")["required_status_checks"]["required_status_checks"]}
    assert required == jobs and len(required) == 6


@pytest.mark.story("CAP-050", "AC3")
def test_rulesets_ac3_codeowners_cover_sensitive_paths():
    lines = [line.split() for line in (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    owners = {parts[0]: parts[1:] for parts in lines}
    assert owners["*"], "every path has an owner"
    for path in ("/.github/", "/scripts/licence-policy.json", "/scripts/github-rulesets.py"):
        assert owners.get(path) == owners["*"], path


@pytest.mark.story("CAP-050", "AC4")
def test_rulesets_ac4_release_tags_immutable():
    tags, create = _ruleset("release-tags"), _ruleset("release-tags-create")
    for r in (tags, create):
        assert r["target"] == "tag" and r["enforcement"] == "active"
        assert r["conditions"]["ref_name"]["include"] == ["refs/tags/v*"]
    assert set(_rules("release-tags")) == {"update", "deletion"} and tags["bypass_actors"] == []
    assert set(_rules("release-tags-create")) == {"creation"}
    assert create["bypass_actors"] == [{**ADMIN, "bypass_mode": "always"}]


@pytest.mark.story("CAP-050", "AC5")
def test_rulesets_ac5_apply_idempotent(capsys):
    github = FakeGitHub()
    assert rs.main(["apply", "--repo", "o/r"], api=github) == 0
    assert sorted(r["name"] for r in github.rulesets.values()) == ["main", "main-review", "release-tags",
                                                                   "release-tags-create"]
    assert github.settings["allow_merge_commit"] is False and github.workflow["default_workflow_permissions"] == "read"
    github.calls.clear()
    assert rs.main(["apply", "--repo", "o/r"], api=github) == 0
    assert github.writes() == []  # the second run only reads
    assert "nothing changed" in capsys.readouterr().out
    assert rs.main(["--check", "--repo", "o/r"], api=github) == 0


@pytest.mark.story("CAP-050", "AC5")
def test_rulesets_ac5_check_reports_drift(capsys):
    github = FakeGitHub()
    rs.main(["apply", "--repo", "o/r"], api=github)
    by_name = {r["name"]: r for r in github.rulesets.values()}
    by_name["main"]["rules"] = [r for r in by_name["main"]["rules"] if r["type"] != "non_fast_forward"]
    by_name["main"]["bypass_actors"].append({**ADMIN, "bypass_mode": "always"})
    by_name["main-review"]["rules"][0]["parameters"]["required_approving_review_count"] = 0
    github.settings["allow_merge_commit"] = True
    capsys.readouterr()
    github.calls.clear()
    assert rs.main(["--check", "--repo", "o/r"], api=github) == 1
    assert github.writes() == []  # --check never writes
    out = capsys.readouterr().out
    assert "main: rule non_fast_forward removed" in out
    assert 'main.bypass_actors: unexpected {"actor_id": 5' in out
    assert "main-review.pull_request.required_approving_review_count: is 0, want 1" in out
    assert "settings.allow_merge_commit: is True, want False" in out
    assert rs.main(["--check", "--report-only", "--repo", "o/r"], api=github) == 0  # the release's dry run
    del github.rulesets[min(github.rulesets)]
    assert rs.main(["--check", "--repo", "o/r"], api=github) == 1 and "ruleset missing" in capsys.readouterr().out


@pytest.mark.story("CAP-050", "AC5")
def test_rulesets_ac5_release_workflow_checks_protection():
    release = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    steps = {s.get("name", ""): s for s in release["jobs"]["check"]["steps"]}
    step = steps["main and v* tags still protected (CAP-050 AC5)"]
    assert "scripts/github-rulesets.py --check" in step["run"] and "exit 1" in step["run"]
    publish = release["jobs"]["publish"]
    assert publish["permissions"]["actions"] == "write"
    assert any("gh workflow run ci.yml" in s.get("run", "") for s in publish["steps"])  # CI on the downloads PR
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "github-rulesets.py apply" in makefile and "github-rulesets.py --check" in makefile
    check = re.search(r"^check:(.*)$", makefile, re.M)
    assert check and "rulesets" not in check[1]  # make check stays offline


@pytest.mark.story("CAP-050", "AC6")
def test_rulesets_ac6_contributing_and_pr_template():
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    section = contributing.split("## How changes reach main", 1)[1].split("\n## ", 1)[0]
    for words in ("Branch from `main`", "pull request", "fork", "code owner", "squash", "make rulesets"):
        assert words in section, words
    template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    assert "## Story" in template and "make check" in template and "make index" in template
