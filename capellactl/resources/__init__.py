"""Resource reconcilers and the dependency tree (00-architecture.md section 4.2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from capellactl.resources.base import Reconciler


def build_tree(cluster_children: list[Reconciler] | None = None) -> Reconciler:
    """project → cluster → (protection, schedule, CIDRs, buckets → scopes → collections, credentials).

    `cluster_children` replaces the default children of the cluster (tests use it to plug in stub
    reconcilers for kinds that later stories implement). Imports are local to avoid import cycles.
    """
    from capellactl.resources.cluster import ClusterReconciler
    from capellactl.resources.project import ProjectReconciler
    from capellactl.resources.unsupported import placeholders

    cluster = ClusterReconciler(children=cluster_children if cluster_children is not None else placeholders())
    return ProjectReconciler(children=[cluster])
