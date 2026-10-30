"""Backup schedule reconcilers: cloud snapshot backups of a cluster (CAP-056) and bucket backups (CAP-058).

Both are optional children: without a `backupSchedule` key in the file an existing schedule is left alone, and only
`drift` and `apply --prune` look for one (most backup endpoints need an Organization or Project Owner key, so plans
made with a Project Manager key must not read them). A schedule the API key may not read is treated as absent.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from typing import Any

from capellactl.api import endpoints as ep
from capellactl.api.errors import Forbidden, NotFound
from capellactl.engine.context import RunContext
from capellactl.resources.base import Action, ActionType, Change, Observed, Reconciler

BUCKET_DEFAULTS: dict[str, Any] = {"dayOfWeek": "sunday", "startAt": 0, "incrementalEvery": 24,
                                   "retentionTime": "30days", "costOptimizedRetention": False}
RETENTION_WORDS = {"30days": "30 days", "60days": "60 days", "90days": "90 days", "180days": "180 days",
                   "1year": "1 year", "2years": "2 years", "3years": "3 years", "4years": "4 years", "5years": "5 years"}


# ------------------------------------------------------------------ cluster (cloud snapshots)
def hours_text(hours: Any) -> str:
    """720 → '30 days', 36 → '36 h'."""
    h = int(hours)
    if h and h % 24 == 0:
        d = h // 24
        return f"{d} day" + ("" if d == 1 else "s")
    return f"{h} h"


def start_hm(value: Any) -> str | None:
    """'02:00' or an ISO 8601 instant → 'HH:MM' in UTC; None when absent or unreadable."""
    if not value:
        return None
    text = str(value)
    if len(text) == 5 and text[2] == ":":
        return text
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is not None:
        t = t.astimezone(timezone.utc)
    return f"{t.hour:02d}:{t.minute:02d}"


def next_instant(hm: str, now: datetime) -> str:
    """The next time of day `hm` (UTC) after `now`, as Capella's startTime."""
    now = now.astimezone(timezone.utc)
    h, m = (int(x) for x in hm.split(":"))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if at <= now:
        at += timedelta(days=1)
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot_summary(body: dict[str, Any]) -> str:
    """`every 24 h · kept 30 days · first at 02:00 UTC · copies: us-west-2`."""
    parts = [f"every {body.get('interval')} h", f"kept {hours_text(body.get('retention') or 0)}"]
    hm = start_hm(body.get("startTime"))
    if hm:
        parts.append(f"first at {hm} UTC")
    if body.get("copyToRegions"):
        parts.append("copies: " + ", ".join(body["copyToRegions"]))
    return " · ".join(parts)


def snapshot_body(desired: dict[str, Any], now: datetime) -> dict[str, Any]:
    body: dict[str, Any] = {"interval": int(desired["interval"]), "retention": int(desired["retention"])}
    if desired.get("startTime"):
        body["startTime"] = next_instant(str(desired["startTime"]), now)
    body["copyToRegions"] = list(desired.get("copyToRegions") or [])
    return body


def options_problem(options: dict[str, Any], desired: dict[str, Any], regions: list[str] | None = None) -> str | None:
    """Why a schedule is outside what the cluster's support plan permits (CAP-056 AC3), or None."""
    intervals = [int(i) for i in options.get("intervals") or []]
    if intervals and int(desired["interval"]) not in intervals:
        return (f"interval {desired['interval']} is not permitted: use one of {', '.join(map(str, intervals))} hours "
                "for this cluster's support plan")
    lo, hi = options.get("minimumRetention"), options.get("maximumRetention")
    ret = int(desired["retention"])
    if (lo is not None and ret < int(lo)) or (hi is not None and ret > int(hi)):
        return (f"retention {hours_text(ret)} is not permitted: keep backups {hours_text(lo or 0)} to "
                f"{hours_text(hi or 0)} for this cluster's support plan")
    copies = list(desired.get("copyToRegions") or [])
    if len(copies) > 2:
        return "copyToRegions takes at most two regions"
    if regions is not None:
        bad = [r for r in copies if r not in regions]
        if bad:
            return f"copies cannot go to {', '.join(bad)}: available regions are {', '.join(regions) or 'none'}"
    return None


def _cluster_ids(cluster: Action | None) -> tuple[str, str]:
    project = cluster.ancestor("project") if cluster is not None else None
    assert cluster is not None and cluster.id is not None and project is not None and project.id is not None
    return project.id, cluster.id


class ClusterBackupScheduleReconciler(Reconciler):
    kind = "backup-schedule"
    story = "CAP-056"
    prunable = True  # `apply --prune` deletes a schedule the file does not declare; `drift` lists it

    def desired_items(self, parent_desired: Any) -> list[Any]:
        if isinstance(parent_desired, dict) and isinstance(parent_desired.get("backupSchedule"), dict):
            return [parent_desired["backupSchedule"]]
        return []

    def key(self, desired: Any, parent: Action | None) -> str:
        return parent.key if parent else ""

    def unmanaged_label(self, observed: Observed, parent: Action | None) -> str:
        return f"backup-schedule {parent.key if parent else ''}  {snapshot_summary(observed.body)}"

    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        if parent is not None and parent.data.get("free"):
            return []  # no backups on the free tier
        pid, cid = _cluster_ids(parent)
        try:
            body = ep.get_snapshot_schedule(ctx.client, pid, cid)
        except (NotFound, Forbidden):
            return []
        return [Observed(cid, body)] if body else []

    def match(self, desired: Any, observed: list[Observed]) -> list[Observed]:
        return observed[:1]

    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        key = self.key(desired, parent)
        if desired.get("ensure") == "absent":
            if observed is None:
                return Action(self.kind, key, ActionType.NOOP, self, desired=desired, parent=parent, hidden=True)
            return Action(self.kind, key, ActionType.DELETE, self, desired=desired, observed=observed, parent=parent,
                          summary=snapshot_summary(observed.body))
        if observed is None:
            a = Action(self.kind, key, ActionType.CREATE, self, desired=desired, parent=parent,
                       summary=snapshot_summary(desired))
        else:
            have = observed.body
            changes = [Change(f, have.get(f), desired[f]) for f in ("interval", "retention")
                       if int(have.get(f) or 0) != int(desired[f])]
            if sorted(have.get("copyToRegions") or []) != sorted(desired.get("copyToRegions") or []):
                changes.append(Change("copyToRegions", have.get("copyToRegions") or [],
                                      desired.get("copyToRegions") or []))
            if desired.get("startTime") and start_hm(have.get("startTime")) != desired["startTime"]:
                changes.append(Change("startTime", start_hm(have.get("startTime")), desired["startTime"]))
            a = Action(self.kind, key, ActionType.UPDATE if changes else ActionType.NOOP, self, desired=desired,
                       observed=observed, parent=parent, changes=changes)
        if a.type is not ActionType.NOOP and parent is not None and parent.id is not None:
            self._check_options(ctx, a, parent)
        return a

    def _check_options(self, ctx: RunContext, action: Action, parent: Action) -> None:
        """Values the support plan does not permit are blocked before any write (CAP-056 AC3)."""
        pid, cid = _cluster_ids(parent)
        try:
            options = ep.get_snapshot_schedule_options(ctx.client, pid, cid)
            regions = ep.list_snapshot_regions(ctx.client, pid, cid) if action.desired.get("copyToRegions") else None
        except (NotFound, Forbidden):
            return  # Capella checks it on the write
        problem = options_problem(options, action.desired, regions)
        if problem:
            action.type, action.reason, action.topic = ActionType.BLOCKED, problem, "backup"

    def delete_action(self, ctx: RunContext, observed: Observed, parent: Action | None) -> Action:
        return Action(self.kind, self.key({}, parent), ActionType.DELETE, self, desired={"ensure": "absent"},
                      observed=observed, parent=parent, summary=snapshot_summary(observed.body))

    def apply(self, ctx: RunContext, action: Action) -> None:
        pid, cid = _cluster_ids(action.parent)
        if action.type is ActionType.DELETE:
            with contextlib.suppress(NotFound):
                ep.delete_snapshot_schedule(ctx.client, pid, cid)
            return
        ep.upsert_snapshot_schedule(ctx.client, pid, cid, snapshot_body(action.desired, ctx.clock.now()))

    def refresh(self, ctx: RunContext, action: Action) -> Action:
        found = self.observe(ctx, action.parent)
        return self.diff(ctx, action.desired, found[0] if found else None, action.parent)


# ------------------------------------------------------------------ bucket backups
def bucket_schedule(desired: dict[str, Any]) -> dict[str, Any]:
    """The file's flat form with defaults → the API's weeklySchedule."""
    return {f: desired.get(f, BUCKET_DEFAULTS[f]) for f in BUCKET_DEFAULTS}


def bucket_summary(weekly: dict[str, Any]) -> str:
    """`weekly full on sunday at 02:00 UTC · incremental every 12 h · kept 90 days`."""
    w = {**BUCKET_DEFAULTS, **weekly}
    text = (f"weekly full on {w['dayOfWeek']} at {int(w['startAt']):02d}:00 UTC · incremental every "
            f"{w['incrementalEvery']} h · kept {RETENTION_WORDS.get(str(w['retentionTime']), w['retentionTime'])}")
    return text + (" · cost-optimized" if w.get("costOptimizedRetention") else "")


def _bucket_ids(bucket: Action | None) -> tuple[str, str, str]:
    cluster = bucket.parent if bucket is not None else None
    project = cluster.ancestor("project") if cluster is not None else None
    assert bucket is not None and cluster is not None and project is not None
    assert project.id and cluster.id and bucket.id
    return project.id, cluster.id, bucket.id


class BucketBackupScheduleReconciler(Reconciler):
    kind = "bucket-backup-schedule"
    story = "CAP-058"
    prunable = True

    def desired_items(self, parent_desired: Any) -> list[Any]:
        if isinstance(parent_desired, dict) and isinstance(parent_desired.get("backupSchedule"), dict):
            return [parent_desired["backupSchedule"]]
        return []

    def key(self, desired: Any, parent: Action | None) -> str:
        return parent.key if parent else ""

    def unmanaged_label(self, observed: Observed, parent: Action | None) -> str:
        return f"bucket-backup-schedule {parent.key if parent else ''}  {bucket_summary(observed.body)}"

    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        cluster = parent.parent if parent is not None else None
        if cluster is not None and cluster.data.get("free"):
            return []
        pid, cid, bid = _bucket_ids(parent)
        try:
            body = ep.get_bucket_backup_schedule(ctx.client, pid, cid, bid)
        except (NotFound, Forbidden):
            return []
        weekly = body.get("weeklySchedule")
        return [Observed(bid, dict(weekly))] if isinstance(weekly, dict) else []

    def match(self, desired: Any, observed: list[Observed]) -> list[Observed]:
        return observed[:1]

    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        key = self.key(desired, parent)
        if desired.get("ensure") == "absent":
            if observed is None:
                return Action(self.kind, key, ActionType.NOOP, self, desired=desired, parent=parent, hidden=True)
            return Action(self.kind, key, ActionType.DELETE, self, desired=desired, observed=observed, parent=parent,
                          summary=bucket_summary(observed.body))
        want = bucket_schedule(desired)
        if observed is None:
            return Action(self.kind, key, ActionType.CREATE, self, desired=desired, parent=parent,
                          summary=bucket_summary(want))
        changes = [Change(f, observed.body.get(f), want[f]) for f in BUCKET_DEFAULTS if observed.body.get(f) != want[f]]
        return Action(self.kind, key, ActionType.UPDATE if changes else ActionType.NOOP, self, desired=desired,
                      observed=observed, parent=parent, changes=changes)

    def delete_action(self, ctx: RunContext, observed: Observed, parent: Action | None) -> Action:
        return Action(self.kind, self.key({}, parent), ActionType.DELETE, self, desired={"ensure": "absent"},
                      observed=observed, parent=parent, summary=bucket_summary(observed.body))

    def apply(self, ctx: RunContext, action: Action) -> None:
        pid, cid, bid = _bucket_ids(action.parent)
        if action.type is ActionType.DELETE:
            with contextlib.suppress(NotFound):
                ep.delete_bucket_backup_schedule(ctx.client, pid, cid, bid)
            return
        body = {"type": "weekly", "weeklySchedule": bucket_schedule(action.desired)}
        if action.type is ActionType.CREATE:
            ep.create_bucket_backup_schedule(ctx.client, pid, cid, bid, body)
        else:
            ep.update_bucket_backup_schedule(ctx.client, pid, cid, bid, body)

    def refresh(self, ctx: RunContext, action: Action) -> Action:
        found = self.observe(ctx, action.parent)
        return self.diff(ctx, action.desired, found[0] if found else None, action.parent)
