"""A dependency tree without the cluster children that later stories implement (deletion protection and
schedules are left out). Allowed CIDRs (CAP-022), buckets (CAP-023), scopes and collections (CAP-025) and
credentials (CAP-027) are the real reconcilers. Test-only: it lets the plan engine and executor (CAP-005/006)
be exercised end to end with a realistic dependency tree.
"""

from __future__ import annotations

from capellactl.resources.allowed_cidr import AllowedCidrReconciler
from capellactl.resources.base import Reconciler
from capellactl.resources.bucket import BucketReconciler
from capellactl.resources.cluster import ClusterReconciler
from capellactl.resources.credential import CredentialReconciler
from capellactl.resources.project import ProjectReconciler
from capellactl.resources.scope import CollectionReconciler, ScopeReconciler


def stub_tree() -> Reconciler:
    """project → cluster → CIDRs, buckets → scopes → collections, credentials."""
    scope = ScopeReconciler(children=[CollectionReconciler()])
    bucket = BucketReconciler(children=[scope])
    cluster = ClusterReconciler(children=[AllowedCidrReconciler(), bucket, CredentialReconciler()])
    return ProjectReconciler(children=[cluster])
