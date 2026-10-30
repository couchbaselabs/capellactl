"""Placeholders for resource kinds that later stories implement, and the default cluster children.

They make no API calls. The plan shows one deferred line per kind per cluster so the file stays
forward-compatible and the operator can see what this build leaves unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from capellactl.engine.context import RunContext
from capellactl.resources.base import Action, ActionType, Observed, Reconciler


class UnsupportedReconciler(Reconciler):
    grouped = True

    def __init__(self, kind: str, stories: str, items: Callable[[dict[str, Any]], list[Any]],
                 describe: Callable[[list[Any]], str]) -> None:
        super().__init__()
        self.kind = kind
        self.story = stories
        self._items = items
        self._describe = describe

    def desired_items(self, parent_desired: Any) -> list[Any]:
        return self._items(parent_desired) if isinstance(parent_desired, dict) else []

    def key(self, desired: Any, parent: Action | None) -> str:
        return f"{parent.key if parent else ''}"

    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        cluster = parent.key if parent else ""
        return Action(
            self.kind, cluster, ActionType.DEFERRED, self, desired=desired, parent=parent,
            summary=self._describe(desired),
            reason=f"not managed by this build yet ({self.story}); left unchanged",
        )


def placeholders() -> list[Reconciler]:
    """Cluster children in dependency order (00-architecture.md section 4.2).

    Every kind is a real reconciler now: deletion protection (CAP-013), the on/off schedule (CAP-020), the cluster
    backup schedule (CAP-056), allowed CIDRs (CAP-022), buckets (CAP-023) and their backup schedules (CAP-058), scopes
    and collections (CAP-025) and database credentials (CAP-027).
    """
    from capellactl.resources.allowed_cidr import AllowedCidrReconciler
    from capellactl.resources.backup_schedule import (
        BucketBackupScheduleReconciler,
        ClusterBackupScheduleReconciler,
    )
    from capellactl.resources.bucket import BucketReconciler
    from capellactl.resources.credential import CredentialReconciler
    from capellactl.resources.deletion_protection import DeletionProtectionReconciler
    from capellactl.resources.schedule import ScheduleReconciler
    from capellactl.resources.scope import CollectionReconciler, ScopeReconciler

    return [
        DeletionProtectionReconciler(),
        ScheduleReconciler(),
        ClusterBackupScheduleReconciler(),  # CAP-056
        AllowedCidrReconciler(),
        BucketReconciler(children=[BucketBackupScheduleReconciler(),  # CAP-058
                                   ScopeReconciler(children=[CollectionReconciler()])]),
        CredentialReconciler(),  # last: after the data model it grants access to (CAP-027 AC7)
    ]
