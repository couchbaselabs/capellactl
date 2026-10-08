"""Deletion protection reconciler (CAP-013).

`deletionProtection: true|false` on a cluster; omitted means leave it unchanged. The current value is the
cluster's own `deletionProtection` field, so planning needs no extra GET. Applied after the cluster is
healthy and before its buckets (it is the cluster's first child, 00-architecture.md section 4.2).
"""

from __future__ import annotations

from typing import Any

from capellactl.api import endpoints as ep
from capellactl.engine.context import RunContext
from capellactl.resources.base import Action, ActionType, Change, Observed, Reconciler


class DeletionProtectionReconciler(Reconciler):
    kind = "deletion-protection"
    story = "CAP-013"

    def desired_items(self, parent_desired: Any) -> list[Any]:
        if isinstance(parent_desired, dict) and "deletionProtection" in parent_desired:
            return [bool(parent_desired["deletionProtection"])]
        return []

    def key(self, desired: Any, parent: Action | None) -> str:
        return parent.key if parent else ""

    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        assert parent is not None and parent.observed is not None
        return [Observed(parent.id, {"deletionProtection": bool(parent.observed.body.get("deletionProtection"))})]

    def match(self, desired: Any, observed: list[Observed]) -> list[Observed]:
        return observed[:1]

    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        key = self.key(desired, parent)
        if observed is None:  # new cluster: Capella creates it unprotected
            if not desired:
                return Action(self.kind, key, ActionType.NOOP, self, desired=desired, parent=parent, hidden=True)
            return Action(self.kind, key, ActionType.CREATE, self, desired=desired, parent=parent,
                          summary="deletionProtection: true")
        current = bool(observed.body.get("deletionProtection"))
        if current == desired:
            return Action(self.kind, key, ActionType.NOOP, self, desired=desired, observed=observed, parent=parent)
        return Action(self.kind, key, ActionType.UPDATE, self, desired=desired, observed=observed, parent=parent,
                      changes=[Change("deletionProtection", current, desired)])

    def apply(self, ctx: RunContext, action: Action) -> None:
        cluster = action.parent
        project = cluster.ancestor("project") if cluster is not None else None
        assert cluster is not None and cluster.id is not None and project is not None and project.id is not None
        ep.set_deletion_protection(ctx.client, project.id, cluster.id, bool(action.desired))
        if cluster.observed is not None:  # later delete guards in the same run see the new value
            cluster.observed.body["deletionProtection"] = bool(action.desired)
