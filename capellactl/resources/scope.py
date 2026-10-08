"""Scope and collection reconcilers: create, and collection maxTTL updates (CAP-025); delete through
`apply --prune` (CAP-026).

The _default and _system scopes and the _default collection are system objects: never created, changed or
deleted. `_default` may be declared so that the collections in it are managed.
"""

from __future__ import annotations

import contextlib
import re
from typing import Any

from capellactl.api import endpoints as ep
from capellactl.api.errors import NotFound
from capellactl.engine.context import RunContext
from capellactl.engine.normalize import field_changes
from capellactl.resources.base import Action, ActionType, Observed, Reconciler
from capellactl.resources.guards import deletion_protected, protection_message

DEFAULT = "_default"
SYSTEM_SCOPES = (DEFAULT, "_system")
MAXTTL_MIN_VERSION = (7, 6, 0)
SYSTEM_DELETE_MESSAGE = "system scopes and collections cannot be deleted"


def is_system_scope(name: Any) -> bool:
    return name in SYSTEM_SCOPES


def is_system_collection(scope: Any, name: Any) -> bool:
    """Every collection of _system, and _default._default."""
    return bool(scope == "_system" or (scope == DEFAULT and name == DEFAULT))


def parse_version(text: Any) -> tuple[int, ...] | None:
    """'7.6.2' → (7, 6, 2); '7.2.4-build' → (7, 2, 4); None when unknown."""
    nums = re.findall(r"\d+", str(text).split("-")[0]) if text else []
    return tuple(int(n) for n in nums[:3]) if nums else None


def server_version(cluster: Action | None) -> tuple[int, ...] | None:
    """Couchbase Server version of a cluster as observed (couchbaseServer.version); None for a new cluster."""
    body = cluster.observed.body if cluster is not None and cluster.observed is not None else {}
    return parse_version((body.get("couchbaseServer") or {}).get("version"))


def _ids(bucket: Action) -> tuple[str, str, str]:
    cluster = bucket.parent
    project = cluster.ancestor("project") if cluster is not None else None
    assert cluster is not None and project is not None and project.id and cluster.id and bucket.id
    return project.id, cluster.id, bucket.id


def _name(action: Action) -> str:
    return str((action.desired or {}).get("name"))


def _protected(cluster: Action | None) -> bool:
    return cluster is not None and cluster.observed is not None and deletion_protected(cluster.observed.body)


def dependent_credentials(client: Any, project_id: str, cluster_id: str, bucket: str, scope: str,
                          collection: str | None = None) -> list[str]:
    """Database credentials whose access names this scope, or this collection (CAP-026 AC5)."""
    names = []
    for u in ep.list_credentials(client, project_id, cluster_id):
        refs = [s for a in u.get("access") or []
                for b in ((a.get("resources") or {}).get("buckets") or []) if b.get("name") == bucket
                for s in b.get("scopes") or [] if s.get("name") == scope]
        if any(collection is None or collection in (s.get("collections") or []) for s in refs):
            names.append(str(u.get("name")))
    return sorted(names)


def delete_details(client: Any, project_id: str, cluster_id: str, bucket: str, bucket_id: str, scope: str,
                   collection: str | None = None) -> list[str]:
    """Confirmation lines for a scope or collection delete: what is lost, then the credentials that lose access."""
    if collection is None:
        body, _ = ep.get_scope(client, project_id, cluster_id, bucket_id, scope)
        colls = sorted(str(c.get("name")) for c in body.get("collections") or [])
        lines = [f"{scope} · {len(colls)} collection{'' if len(colls) == 1 else 's'}" +
                 (f": {', '.join(colls)}" if colls else "")]
        if colls:
            lines.append("These collections and all their documents are deleted.")
        what = "scope"
    else:
        lines = [f"{scope}.{collection} and all its documents are deleted."]
        what = "collection"
    creds = dependent_credentials(client, project_id, cluster_id, bucket, scope, collection)
    if creds:
        lines.append(f"These credentials lose access to this {what}:")
        lines += [f"  {c}" for c in creds]
    return lines


class ScopeReconciler(Reconciler):
    kind = "scope"
    story = "CAP-025"
    prunable = True
    reports_unmanaged = True

    def desired_items(self, parent_desired: Any) -> list[Any]:
        return list(parent_desired.get("scopes") or []) if isinstance(parent_desired, dict) else []

    def key(self, desired: Any, parent: Action | None) -> str:
        return f"{parent.key}/{desired['name']}" if parent else str(desired["name"])

    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        assert parent is not None
        return [Observed(str(s["name"]), s) for s in ep.list_scopes(ctx.client, *_ids(parent))]

    def manages(self, observed: Observed) -> bool:
        return not is_system_scope(observed.body.get("name"))

    def after_children_note(self) -> str:
        return "(after scope is created)"

    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        key = self.key(desired, parent)
        if observed is not None or desired.get("name") == DEFAULT:  # _default exists with every bucket
            return Action(self.kind, key, ActionType.NOOP, self, desired=desired, observed=observed, parent=parent)
        return Action(self.kind, key, ActionType.CREATE, self, desired=desired, parent=parent)

    def delete_action(self, ctx: RunContext, observed: Observed, parent: Action | None) -> Action:
        """`apply --prune`: a scope the file no longer declares (CAP-026 AC4)."""
        a = Action(self.kind, f"{parent.key}/{observed.body.get('name')}" if parent else str(observed.id),
                   ActionType.DELETE, self, desired={"name": observed.body.get("name")}, observed=observed,
                   parent=parent)
        cluster = parent.parent if parent is not None else None
        if _protected(cluster):
            assert cluster is not None
            a.type, a.topic, a.reason = ActionType.BLOCKED, "safety", protection_message(cluster.key)
        return a

    def apply(self, ctx: RunContext, action: Action) -> None:
        assert action.parent is not None
        if action.type is ActionType.CREATE:
            ep.create_scope(ctx.client, *_ids(action.parent), _name(action))
            action.created_id = _name(action)
        elif action.type is ActionType.DELETE:
            with contextlib.suppress(NotFound):  # already gone: the goal is reached
                ep.delete_scope(ctx.client, *_ids(action.parent), _name(action))


class CollectionReconciler(Reconciler):
    kind = "collection"
    story = "CAP-025"
    prunable = True
    reports_unmanaged = True

    def desired_items(self, parent_desired: Any) -> list[Any]:
        return list(parent_desired.get("collections") or []) if isinstance(parent_desired, dict) else []

    def key(self, desired: Any, parent: Action | None) -> str:
        return f"{parent.key}/{desired['name']}" if parent else str(desired["name"])

    def _where(self, scope: Action) -> tuple[str, str, str, str]:
        assert scope.parent is not None
        return (*_ids(scope.parent), _name(scope))

    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        assert parent is not None
        scope = _name(parent)
        return [Observed(str(c["name"]), c) for c in ep.list_collections(ctx.client, *self._where(parent))
                if not is_system_collection(scope, c.get("name"))]

    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        key = self.key(desired, parent)
        if observed is None:
            summary = f"maxTTL {desired['maxTTL']}" if "maxTTL" in desired else None
            return Action(self.kind, key, ActionType.CREATE, self, desired=desired, parent=parent, summary=summary)
        a = Action(self.kind, key, ActionType.NOOP, self, desired=desired, observed=observed, parent=parent)
        # maxTTL is compared only when the file declares it (CAP-025 AC4)
        changes = field_changes({"maxTTL": desired["maxTTL"]} if "maxTTL" in desired else {}, observed.body)
        if not changes:
            return a
        a.changes = changes
        cluster = parent.ancestor("cluster") if parent is not None else None
        version = server_version(cluster)
        if version is not None and version < MAXTTL_MIN_VERSION:
            a.type, a.topic = ActionType.BLOCKED, "idempotency"
            a.reason = ("maxTTL can only be changed on Couchbase Server 7.6.0 or later "
                        f"({cluster.key if cluster else 'the cluster'} runs {'.'.join(map(str, version))})")
            return a
        a.type = ActionType.UPDATE
        return a

    def delete_action(self, ctx: RunContext, observed: Observed, parent: Action | None) -> Action:
        """`apply --prune`: a collection the file no longer declares (CAP-026 AC4)."""
        a = Action(self.kind, f"{parent.key}/{observed.body.get('name')}" if parent else str(observed.id),
                   ActionType.DELETE, self, desired={"name": observed.body.get("name")}, observed=observed,
                   parent=parent)
        cluster = parent.ancestor("cluster") if parent is not None else None
        if _protected(cluster):
            assert cluster is not None
            a.type, a.topic, a.reason = ActionType.BLOCKED, "safety", protection_message(cluster.key)
        return a

    def apply(self, ctx: RunContext, action: Action) -> None:
        assert action.parent is not None
        where = self._where(action.parent)
        d = action.desired
        if action.type is ActionType.CREATE:
            ep.create_collection(ctx.client, *where, {k: d[k] for k in ("name", "maxTTL") if k in d})
            action.created_id = _name(action)
        elif action.type is ActionType.UPDATE:
            current, etag = ep.get_collection(ctx.client, *where, _name(action))
            if field_changes({"maxTTL": d["maxTTL"]}, current):  # 412 on a stale ETag: the executor re-plans
                ep.update_collection(ctx.client, *where, _name(action), d["maxTTL"], if_match=etag)
        elif action.type is ActionType.DELETE:
            with contextlib.suppress(NotFound):
                ep.delete_collection(ctx.client, *where, _name(action))
