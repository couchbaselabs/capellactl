"""Bucket reconciler: create and update (CAP-023), delete through `apply --prune` (CAP-024).

Free-tier clusters have their own bucket endpoints (…/buckets/freeTier), where only memoryAllocationInMb
(and, on update, enableCrossClusterVersioning) can be set; everything else uses Capella's defaults.

Scopes and collections below a bucket are child reconcilers (resources/scope.py, CAP-025).
"""

from __future__ import annotations

import contextlib
from typing import Any

from capellactl.api import endpoints as ep
from capellactl.api.errors import CapellaApiError, NotFound
from capellactl.engine.context import RunContext
from capellactl.engine.normalize import canon_flush, field_changes
from capellactl.resources.base import Action, ActionType, Change, Observed, Reconciler
from capellactl.resources.guards import deletion_protected, protection_message

CREATE_FIELDS = ["name", "type", "storageBackend", "vbuckets", "memoryAllocationInMb", "bucketConflictResolution",
                 "durabilityLevel", "replicas", "flushEnabled", "timeToLiveInSeconds", "evictionPolicy", "priority"]
IMMUTABLE = ["type", "storageBackend", "vbuckets", "bucketConflictResolution", "evictionPolicy"]
UPDATE_REQUIRED = ["memoryAllocationInMb", "durabilityLevel", "replicas", "timeToLiveInSeconds"]
UPDATE_OPTIONAL = ["flushEnabled", "enableCrossClusterVersioning", "priority"]
UPDATABLE = UPDATE_REQUIRED + UPDATE_OPTIONAL
FREE_UPDATABLE = ["memoryAllocationInMb", "enableCrossClusterVersioning"]
REPLICA_NOTE = "note: the new replica count takes full effect after a rebalance"
ONE_NODE_NOTE = "note: the cluster has one data node; the replica is placed when data nodes are added"


def is_free_cluster(cluster: Action | None) -> bool:
    return bool(cluster is not None and cluster.data.get("free"))


def observed_view(body: dict[str, Any]) -> dict[str, Any]:
    """The bucket as compared: flushEnabled read from the deprecated flush only when absent (section 6.3)."""
    view = dict(body)
    flush = canon_flush(body)
    view.pop("flush", None)
    if flush is not None:
        view["flushEnabled"] = flush
    return view


def _plural(n: Any, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def create_summary(d: dict[str, Any], free: bool = False) -> str:
    """`couchbase · magma · 1024 MB · 1 replica · durability majority` (CAP-023 AC1); free tier: `free tier · 100 MB`."""
    if free:
        return f"free tier · {d.get('memoryAllocationInMb', 100)} MB"
    parts = [str(d.get("type", "couchbase"))]
    if d.get("storageBackend"):
        parts.append(str(d["storageBackend"]))
    if d.get("memoryAllocationInMb") is not None:
        parts.append(f"{d['memoryAllocationInMb']} MB")
    if d.get("replicas") is not None:
        parts.append(_plural(d["replicas"], "replica"))
    if d.get("durabilityLevel"):
        parts.append(f"durability {d['durabilityLevel']}")
    return " · ".join(parts)


def build_update_body(observed: dict[str, Any], desired: dict[str, Any], free: bool = False) -> dict[str, Any]:
    """Full PUT body: observed overlaid with desired (00-architecture.md section 6.4)."""
    if free:
        body = {f: observed[f] for f in FREE_UPDATABLE if observed.get(f) is not None}
        body.update({f: desired[f] for f in FREE_UPDATABLE if f in desired})
        return body
    view = observed_view(observed)
    body = {f: view.get(f) for f in UPDATE_REQUIRED}
    body.update({f: view[f] for f in UPDATE_OPTIONAL if view.get(f) is not None})
    body.update({f: desired[f] for f in UPDATABLE if f in desired})
    return body


def bucket_changes(desired: dict[str, Any], observed: dict[str, Any],
                   free: bool = False) -> tuple[list[Change], list[Change]]:
    """(immutable changes, updatable changes) for fields present in the file."""
    view = observed_view(observed)
    view.setdefault("enableCrossClusterVersioning", False)
    if free:  # nothing else can be set on a free-tier bucket
        return [], field_changes({f: desired[f] for f in FREE_UPDATABLE if f in desired}, view)
    immutable = field_changes({f: desired[f] for f in IMMUTABLE if f in desired}, view)
    updatable = field_changes({f: desired[f] for f in UPDATABLE if f in desired}, view)
    return immutable, updatable


def dependent_credentials(client: Any, project_id: str, cluster_id: str, bucket: str) -> list[str]:
    """Database credentials whose access names this bucket (CAP-024 AC3)."""
    names = []
    for u in ep.list_credentials(client, project_id, cluster_id):
        for a in u.get("access") or []:
            if any(b.get("name") == bucket for b in ((a.get("resources") or {}).get("buckets") or [])):
                names.append(str(u.get("name")))
                break
    return sorted(names)


def delete_details(client: Any, project_id: str, cluster_id: str, body: dict[str, Any]) -> list[str]:
    """Confirmation lines for a bucket delete: size, then the credentials that lose access."""
    stats = body.get("stats") or {}  # itemCount, opsPerSecond, diskUsedInMib, memoryUsedInMib
    line = f"{body.get('name')} · {int(stats.get('itemCount') or 0):,} items"
    if stats.get("memoryUsedInMib") is not None:
        line += f" · {stats['memoryUsedInMib']} MB used"
    lines = [line]
    creds = dependent_credentials(client, project_id, cluster_id, str(body.get("name")))
    if creds:
        lines.append("These credentials lose access to this bucket:")
        lines += [f"  {c}" for c in creds]
    return lines


class BucketReconciler(Reconciler):
    kind = "bucket"
    story = "CAP-023"
    prunable = True

    def __init__(self, children: list[Reconciler] | None = None) -> None:
        super().__init__(children)
        # Per cluster id: cluster stats, and memory still free after the creates/increases planned so far.
        self._stats: dict[str, dict[str, Any] | None] = {}
        self._free: dict[str, int] = {}

    def desired_items(self, parent_desired: Any) -> list[Any]:
        return list(parent_desired.get("buckets") or []) if isinstance(parent_desired, dict) else []

    def key(self, desired: Any, parent: Action | None) -> str:
        return f"{parent.key}/{desired['name']}" if parent else str(desired["name"])

    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        assert parent is not None and parent.id is not None
        self._stats.pop(parent.id, None)
        self._free.pop(parent.id, None)
        if is_free_cluster(parent):
            buckets, stats = ep.list_free_buckets(ctx.client, *self._ids(parent))
            self._remember_stats(parent.id, stats)
            return [Observed(str(b["id"]), b) for b in buckets]
        return [Observed(str(b["id"]), b) for b in ep.list_buckets(ctx.client, *self._ids(parent))]

    def after_children_note(self) -> str:
        return "(after bucket is created)"

    # --------------------------------------------------------------- capacity
    def _ids(self, cluster: Action) -> tuple[str, str]:
        project = cluster.ancestor("project")
        assert project is not None and project.id is not None and cluster.id is not None
        return project.id, cluster.id

    def _remember_stats(self, cluster_id: str, stats: dict[str, Any] | None) -> None:
        self._stats[cluster_id] = stats or None
        if stats and stats.get("freeMemoryInMb") is not None:
            self._free[cluster_id] = int(stats["freeMemoryInMb"])

    def _cluster_stats(self, ctx: RunContext, cluster: Action | None) -> dict[str, Any] | None:
        """GET …/stats once per cluster and plan (free tier: the bucket list's clusterStats); None when the
        cluster does not exist yet or has no stats."""
        if cluster is None or cluster.observed is None or cluster.id is None:
            return None
        if cluster.id not in self._stats:
            try:
                stats: dict[str, Any] | None = ep.get_cluster_stats(ctx.client, *self._ids(cluster))
            except CapellaApiError:
                stats = None
            self._remember_stats(cluster.id, stats)
        return self._stats[cluster.id]

    def _preflight(self, ctx: RunContext, cluster: Action | None, need_mb: int, replicas: Any,
                   check_replicas: bool) -> tuple[str | None, list[str]]:
        """(blocked reason, notes) for the cluster's free memory and data nodes (CAP-023 AC6)."""
        stats = self._cluster_stats(ctx, cluster)
        if stats is None or cluster is None or cluster.id is None:
            return None, []
        notes: list[str] = []
        max_replicas = stats.get("maxReplicas")
        if check_replicas and isinstance(replicas, int) and isinstance(max_replicas, int) and replicas > max_replicas:
            # The API's minimum is 1 replica, so a cluster with one data node (maxReplicas 0) still accepts 1.
            allowed = max(max_replicas, 1)
            if replicas > allowed:
                return (f"replicas: {replicas} but the cluster supports at most {allowed}; scale out (CAP-015) "
                        "or reduce replicas"), []
            notes.append(ONE_NODE_NOTE)
        if need_mb > 0 and cluster.id in self._free:
            free = self._free[cluster.id]
            if need_mb > free:
                return (f"needs {need_mb} MB but the cluster has {free} MB free; scale out (CAP-015) or reduce "
                        "memoryAllocationInMb"), []
            self._free[cluster.id] = free - need_mb
        return None, notes

    # --------------------------------------------------------------- planning
    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        key = self.key(desired, parent)
        free = is_free_cluster(parent)
        if observed is None:
            a = Action(self.kind, key, ActionType.CREATE, self, desired=desired, parent=parent,
                       summary=create_summary(desired, free))
            need = int(desired.get("memoryAllocationInMb") or (100 if free else 0))
            blocked, notes = self._preflight(ctx, parent, need, desired.get("replicas"), check_replicas=not free)
            if blocked:
                a.type, a.reason, a.topic = ActionType.BLOCKED, blocked, "scaling"
            a.notes += notes
            return a
        a = Action(self.kind, key, ActionType.NOOP, self, desired=desired, observed=observed, parent=parent)
        immutable, changes = bucket_changes(desired, observed.body, free)
        if immutable:
            a.type, a.topic = ActionType.BLOCKED, "idempotency"
            a.reason = "; ".join(f"{c.path}: {c.before} → {c.after}" for c in immutable) + \
                "  BLOCKED (immutable; create a new bucket and migrate data)"
            return a
        if not changes:
            return a
        a.type, a.changes = ActionType.UPDATE, changes
        by_path = {c.path: c for c in changes}
        mem = by_path.get("memoryAllocationInMb")
        increase = mem.after - mem.before if mem and isinstance(mem.before, int) and isinstance(mem.after, int) else 0
        blocked, notes = self._preflight(ctx, parent, max(increase, 0), desired.get("replicas"),
                                         check_replicas="replicas" in by_path)
        if blocked:
            a.type, a.reason, a.topic = ActionType.BLOCKED, blocked, "scaling"
            return a
        if "replicas" in by_path:
            a.notes.append(REPLICA_NOTE)
        a.notes += notes
        return a

    def delete_action(self, ctx: RunContext, observed: Observed, parent: Action | None) -> Action:
        """`apply --prune`: a bucket in Capella that the file no longer declares (CAP-024 AC4)."""
        key = f"{parent.key}/{observed.body.get('name')}" if parent else str(observed.body.get("name"))
        a = Action(self.kind, key, ActionType.DELETE, self, desired={"name": observed.body.get("name")},
                   observed=observed, parent=parent)
        if parent is not None and parent.observed is not None and deletion_protected(parent.observed.body):
            a.type, a.topic, a.reason = ActionType.BLOCKED, "safety", protection_message(parent.key)
        return a

    # --------------------------------------------------------------- applying
    def apply(self, ctx: RunContext, action: Action) -> None:
        assert action.parent is not None
        pid, cid = self._ids(action.parent)
        d = action.desired
        if is_free_cluster(action.parent):
            self._apply_free(ctx, action, pid, cid)
            return
        if action.type is ActionType.CREATE:
            body = {k: d[k] for k in CREATE_FIELDS if k in d}  # flushEnabled, never the deprecated flush
            action.created_id = ep.create_bucket(ctx.client, pid, cid, body)
            if d.get("enableCrossClusterVersioning"):  # only accepted by the update endpoint
                current, _ = ep.get_bucket(ctx.client, pid, cid, action.created_id)
                ep.update_bucket(ctx.client, pid, cid, action.created_id, build_update_body(current, d))
            return
        assert action.observed is not None and action.observed.id is not None
        bid = action.observed.id
        if action.type is ActionType.UPDATE:
            current, _ = ep.get_bucket(ctx.client, pid, cid, bid)
            if bucket_changes(d, current)[1]:
                ep.update_bucket(ctx.client, pid, cid, bid, build_update_body(current, d))
            return
        if action.type is ActionType.DELETE:
            with contextlib.suppress(NotFound):  # already gone: the goal is reached
                ep.delete_bucket(ctx.client, pid, cid, bid)

    def _apply_free(self, ctx: RunContext, action: Action, pid: str, cid: str) -> None:
        d = action.desired
        if action.type is ActionType.CREATE:
            body = {k: d[k] for k in ("name", "memoryAllocationInMb") if k in d}
            action.created_id = ep.create_free_bucket(ctx.client, pid, cid, body)
            if d.get("enableCrossClusterVersioning"):  # only accepted by the update endpoint
                current, _ = ep.get_free_bucket(ctx.client, pid, cid, action.created_id)
                ep.update_free_bucket(ctx.client, pid, cid, action.created_id, build_update_body(current, d, free=True))
            return
        assert action.observed is not None and action.observed.id is not None
        bid = action.observed.id
        if action.type is ActionType.UPDATE:
            current, _ = ep.get_free_bucket(ctx.client, pid, cid, bid)
            if bucket_changes(d, current, free=True)[1]:
                ep.update_free_bucket(ctx.client, pid, cid, bid, build_update_body(current, d, free=True))
        elif action.type is ActionType.DELETE:
            with contextlib.suppress(NotFound):
                ep.delete_free_bucket(ctx.client, pid, cid, bid)
