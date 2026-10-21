#!/usr/bin/env python3
"""Delete the nightly integration suite's leftover projects (CAP-032 AC3). The weekly `janitor` job runs this.

Usage: python scripts/ci-janitor.py [--prefix capellactl-ci-] [--older-than-hours 24] [--dry-run] [--fail-on-leftovers]

Every project whose name starts with the prefix and that was created more than --older-than-hours ago is deleted
with everything in it: deletion protection is turned off, each cluster is deleted (snapshot backups discarded) and
waited for, then the project is deleted. The suite's own teardown (tests/integration) uses the same
`delete_project_tree`, so a leftover means a run was killed before its teardown could run. With
--fail-on-leftovers the job then fails, so the leak is noticed.

Credentials: CAPELLA_SANDBOX_API_KEY and CAPELLA_SANDBOX_ORG_ID (or CAPELLA_API_KEY and CAPELLA_ORG_ID).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

from capellactl.api import endpoints as ep
from capellactl.api.client import CapellaClient
from capellactl.api.errors import CapellaApiError, NotFound
from capellactl.engine.clock import Clock, get_clock
from capellactl.engine.waiter import wait_for_cluster
from capellactl.resources.cluster import is_free

PREFIX = "capellactl-ci-"
RETRY_SECONDS = 60  # a cluster that is still deploying or scaling refuses deletion; ask again this often


def created_at(project: dict[str, Any]) -> datetime | None:
    raw = str((project.get("audit") or {}).get("createdAt") or "")
    # Python 3.10 reads neither "Z" nor more than 6 fractional digits
    raw = re.sub(r"(\.\d{6})\d+", r"\1", raw.replace("Z", "+00:00"))
    try:
        born = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return born if born.tzinfo else born.replace(tzinfo=timezone.utc)


def stale(projects: list[dict[str, Any]], prefix: str, older_than: timedelta, now: datetime) -> list[dict[str, Any]]:
    """The projects named prefix* created before now - older_than. One without a readable creation time is kept:
    it may belong to a run in progress."""
    out = []
    for p in projects:
        if not str(p.get("name", "")).startswith(prefix):
            continue
        born = created_at(p)
        if born is None:
            print(f"skipping {p.get('name')}: no readable audit.createdAt", file=sys.stderr)
        elif now - born > older_than:
            out.append(p)
    return out


def _retry(clock: Clock, timeout: timedelta, what: str, call: Callable[[], None]) -> None:
    start = clock.monotonic()
    while True:
        try:
            call()
            return
        except NotFound:
            return
        except CapellaApiError:
            if clock.monotonic() - start + RETRY_SECONDS > timeout.total_seconds():
                raise
            print(f"  {what}: refused for now, trying again in {RETRY_SECONDS}s", file=sys.stderr)
            clock.sleep(RETRY_SECONDS)


def delete_project_tree(client: CapellaClient, project: dict[str, Any], timeout: timedelta = timedelta(minutes=60),
                        clock: Clock | None = None) -> list[str]:
    """Delete one project and everything in it; returns what was done, in order."""
    clock = clock or get_clock()
    pid, pname = str(project["id"]), str(project.get("name"))
    done: list[str] = []
    try:
        clusters = ep.list_clusters(client, pid)
    except NotFound:
        return done
    for c in clusters:
        cid, cname, free = str(c["id"]), str(c.get("name")), is_free(c)
        if c.get("deletionProtection"):
            ep.set_deletion_protection(client, pid, cid, False)
            done.append(f"deletion protection off for {cname}")
        delete = partial(ep.delete_free_cluster, client, pid, cid) if free else partial(
            ep.delete_cluster, client, pid, cid, retain_snapshot_backups=False)
        _retry(clock, timeout, f"delete cluster {cname}", delete)
    for c in clusters:
        cid, cname = str(c["id"]), str(c.get("name"))
        wait_for_cluster(client, pid, cid, "delete", timeout, clock, name=cname,
                         getter=ep.get_free_cluster if is_free(c) else None)
        done.append(f"deleted cluster {cname}")
    _retry(clock, timeout, f"delete project {pname}", lambda: ep.delete_project(client, pid))
    done.append(f"deleted project {pname}")
    return done


def delete_projects_named(client: CapellaClient, name: str, timeout: timedelta = timedelta(minutes=60),
                          clock: Clock | None = None) -> list[str]:
    """Delete every project called `name` (a test's own teardown; normally there is one, or none left)."""
    done: list[str] = []
    for p in ep.list_projects(client):
        if p.get("name") == name:
            done += delete_project_tree(client, p, timeout, clock)
    return done


def sandbox_client() -> CapellaClient:
    key = os.environ.get("CAPELLA_SANDBOX_API_KEY") or os.environ.get("CAPELLA_API_KEY")
    org = os.environ.get("CAPELLA_SANDBOX_ORG_ID") or os.environ.get("CAPELLA_ORG_ID")
    if not key or not org:
        raise SystemExit("ci-janitor: set CAPELLA_SANDBOX_API_KEY and CAPELLA_SANDBOX_ORG_ID")
    return CapellaClient(key, org, clock=get_clock())


def main(argv: list[str] | None = None, client: CapellaClient | None = None, now: datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prefix", default=PREFIX)
    ap.add_argument("--older-than-hours", type=float, default=24.0)
    ap.add_argument("--dry-run", action="store_true", help="only list what would be deleted")
    ap.add_argument("--fail-on-leftovers", action="store_true", help="exit 1 when anything was left over")
    ap.add_argument("--timeout-minutes", type=float, default=60.0)
    a = ap.parse_args(argv)
    client = client or sandbox_client()
    now = now or datetime.now(timezone.utc)
    found = stale(ep.list_projects(client), a.prefix, timedelta(hours=a.older_than_hours), now)
    if not found:
        print(f"no {a.prefix}* projects older than {a.older_than_hours:g} hours")
        return 0
    failed = 0
    for p in found:
        print(f"leftover project {p.get('name')} (created {(p.get('audit') or {}).get('createdAt', 'unknown')})")
        if a.dry_run:
            continue
        try:
            for step in delete_project_tree(client, p, timedelta(minutes=a.timeout_minutes)):
                print(f"  {step}")
        except Exception as exc:  # noqa: BLE001 - report every project, then fail
            failed += 1
            print(f"  FAILED: {exc}", file=sys.stderr)
    print(f"{len(found)} leftover project(s){'' if a.dry_run else ' deleted'}, {failed} failed")
    return 1 if failed or a.fail_on_leftovers else 0


if __name__ == "__main__":
    sys.exit(main())
