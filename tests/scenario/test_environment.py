"""CAP-030: build a whole environment with apply, and tear it down with destroy."""
from __future__ import annotations

import re
import shutil

import pytest

from capellactl.cli import console
from tests.conftest import EXAMPLE

ENV = {"ORDERS_APP_PASSWORD": "Orders#App-123"}
KINDS = [("POST", r"/projects$", "project"), ("POST", r"/clusters$", "cluster"),
         ("PUT", r"/deletionProtection$", "deletion-protection"), ("POST", r"/onOffSchedule$", "schedule"),
         ("POST", r"/allowedcidrs$", "cidr"), ("POST", r"/buckets$", "bucket"), ("POST", r"/scopes$", "scope"),
         ("POST", r"/collections$", "collection"), ("POST", r"/users$", "credential"),
         ("DELETE", r"/users/[^/]+$", "credential"), ("DELETE", r"/collections/[^/]+$", "collection"),
         ("DELETE", r"/scopes/[^/]+$", "scope"), ("DELETE", r"/buckets/[^/]+$", "bucket"),
         ("DELETE", r"/allowedcidrs/[^/]+$", "cidr"), ("DELETE", r"/onOffSchedule$", "schedule"),
         ("DELETE", r"/clusters/[^/]+$", "cluster"), ("DELETE", r"/projects/[^/]+$", "project")]


def _kinds(calls):
    out = []
    for c in calls:
        for method, rx, kind in KINDS:
            if c.method == method and re.search(rx, c.path):
                out.append(kind)
                break
    return out


def _runs(kinds):
    """['project', 'cluster', 'cluster'] → ['project', 'cluster'] (each kind once, in first-seen order)."""
    seen: list[str] = []
    for k in kinds:
        if not seen or seen[-1] != k:
            seen.append(k)
    return seen


@pytest.fixture
def example(tmp_path):
    shutil.copy(EXAMPLE, tmp_path / "capella.yaml")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "reporting_ro.txt").write_text("R3port!ng-pw")
    return tmp_path / "capella.yaml"


@pytest.fixture
def built(fake, run, example):
    r = run("--auto-approve", "apply", extra_env=ENV)
    assert r.exit_code == 0, r.output
    return r


@pytest.mark.story("CAP-030", "AC1")
def test_env_ac1_full_build_order(fake, built):
    order = _runs(_kinds(fake.writes()))
    assert order == ["project", "cluster", "deletion-protection", "schedule", "cidr", "bucket", "scope", "collection",
                     "credential"]


@pytest.mark.story("CAP-030", "AC1")
def test_env_ac1_summary_table(fake, built):
    lines = built.output
    for kind, name in [("project", "nova-dev"), ("cluster", "nova-dev-01"), ("schedule", "nova-dev-01"),
                       ("bucket", "nova-dev-01/orders"), ("collection", "nova-dev-01/orders/inventory/items"),
                       ("credential", "nova-dev-01/orders_app")]:
        assert re.search(rf"^{re.escape(kind)}\s+{re.escape(name)}\s+create\s+done\s", lines, flags=re.M), (kind, lines)
    assert "connectionString (nova-dev-01): couchbases://cb." in lines


@pytest.mark.story("CAP-030", "AC2")
def test_env_ac2_second_run_zero_writes(fake, run, built):
    fake.reset_calls()
    r = run("--auto-approve", "apply", extra_env=ENV)
    assert r.exit_code == 0 and "No changes" in r.output and fake.writes() == []


@pytest.mark.story("CAP-030", "AC3")
def test_env_ac3_resume_after_failure(fake, run, example):
    fake.fail_next("POST", "*/scopes", 422, 4000)
    r = run("--auto-approve", "apply", extra_env=ENV)
    assert r.exit_code == 1, r.output
    first = _kinds([c for c in fake.writes()])
    assert "scope" in first and "collection" not in first and "credential" not in first
    fake.reset_calls()
    r = run("--auto-approve", "apply", extra_env=ENV)
    assert r.exit_code == 0, r.output
    second = _runs(_kinds(fake.writes()))
    assert second == ["scope", "collection", "credential"]  # nothing created twice
    assert len(fake.projects) == 1 and len(fake.clusters) == 1 and len(fake.buckets) == 2


def _unprotect(fake):
    for c in fake.clusters.values():
        c["body"]["deletionProtection"] = False


@pytest.mark.story("CAP-030", "AC4")
def test_env_ac4_destroy_reverse_order(fake, run, built, monkeypatch, tmp_path):
    _unprotect(fake)
    fake.reset_calls()
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("destroy", input="nova-dev\n", extra_env=ENV)
    assert r.exit_code == 0, r.output
    assert _runs(_kinds(fake.writes())) == ["credential", "collection", "scope", "bucket", "cidr", "schedule",
                                            "cluster", "project"]
    assert "cluster nova-dev-01: deleted (" in r.output and "Destroy complete in" in r.output
    assert fake.projects == {} and fake.clusters == {}
    # the ids of what was deleted are dropped (a pinned id that is gone stops apply); the rest of the file stays
    assert "id:" not in (tmp_path / "capella.yaml").read_text()
    r = run("plan", extra_env=ENV)
    assert r.exit_code == 0 and "+ project nova-dev" in r.output and "+ cluster nova-dev-01" in r.output


@pytest.mark.story("CAP-030", "AC5")
def test_env_ac5_destroy_blocked_by_protection(fake, run, built):
    fake.reset_calls()
    r = run("--auto-approve", "destroy", extra_env=ENV)
    assert r.exit_code == 4 and "deletion protection is on for nova-dev-01" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-030", "AC6")
def test_env_ac6_destroy_keeps_project_with_undeclared(fake, run, built):
    _unprotect(fake)
    pid = next(iter(fake.projects))
    fake.seed_cluster(pid, "someone-else")
    r = run("--auto-approve", "destroy", extra_env=ENV)
    assert r.exit_code == 0, r.output
    assert "project nova-dev kept: contains undeclared cluster someone-else" in r.output
    assert pid in fake.projects and [c["body"]["name"] for c in fake.clusters.values()] == ["someone-else"]


@pytest.mark.story("CAP-030", "AC7")
def test_env_ac7_destroy_nothing(fake, run, example):
    r = run("--auto-approve", "destroy", extra_env=ENV)
    assert r.exit_code == 0 and "nothing to destroy" in r.output, r.output
    assert fake.writes() == []
