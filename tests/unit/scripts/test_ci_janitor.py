"""CAP-032 AC3: the weekly janitor deletes leftover capellactl-ci-* projects older than 24 hours."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from capellactl.api.client import CapellaClient
from tests.conftest import API_KEY, ORG
from tests.integration.harness import janitor

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _seed(fake, name, age_hours, protected=False):
    pid = fake.seed_project(name)
    fake.projects[pid]["audit"]["createdAt"] = (NOW - timedelta(hours=age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fake.seed_cluster(pid, f"{name}-01", deletionProtection=protected)
    return pid


@pytest.fixture
def client(fake, clock):
    return CapellaClient(API_KEY, ORG, clock=clock)


@pytest.mark.story("CAP-032", "AC3")
def test_janitor_deletes_only_old_ci_projects(fake, client, capsys):
    old = _seed(fake, "capellactl-ci-111-1-shared", 30, protected=True)
    young = _seed(fake, "capellactl-ci-222-1-shared", 2)
    other = _seed(fake, "nova-dev", 500)
    assert janitor.main([], client=client, now=NOW) == 0
    assert old not in fake.projects and {young, other} <= set(fake.projects)
    out = capsys.readouterr().out
    assert "leftover project capellactl-ci-111-1-shared" in out and "deletion protection off" in out
    assert "1 leftover project(s) deleted, 0 failed" in out


@pytest.mark.story("CAP-032", "AC3")
def test_janitor_reports_leftovers_and_clean_runs(fake, client, capsys):
    _seed(fake, "capellactl-ci-111-1-life", 30)
    assert janitor.main(["--dry-run", "--fail-on-leftovers"], client=client, now=NOW) == 1
    assert len(fake.projects) == 1  # dry run: nothing deleted
    assert janitor.main(["--fail-on-leftovers"], client=client, now=NOW) == 1  # cleaned, but the leak is reported
    assert fake.projects == {}
    assert janitor.main(["--fail-on-leftovers"], client=client, now=NOW) == 0
    assert "no capellactl-ci-* projects older than 24 hours" in capsys.readouterr().out


@pytest.mark.parametrize("stamp,stale", [("2026-10-19T10:00:00Z", True), ("2026-10-19T10:00:00.123456789Z", True),
                                         ("2026-10-20T10:00:00+00:00", False), ("not a date", False), ("", False)])
def test_janitor_reads_capella_timestamps(stamp, stale):
    p = {"name": "capellactl-ci-1", "audit": {"createdAt": stamp}}
    assert bool(janitor.stale([p], "capellactl-ci-", timedelta(hours=24), NOW)) is stale
