"""Safety checks shared by every delete path (CAP-013 AC4).

cluster delete, bucket delete, destroy, `apply --prune` (buckets) and `project delete --cascade` all ask
`deletion_protected` before any API write, and refuse with `protection_message`.
"""

from __future__ import annotations

from typing import Any


def deletion_protected(cluster: dict[str, Any] | None) -> bool:
    """True when the cluster (as returned by GET or list) has deletion protection on."""
    return bool((cluster or {}).get("deletionProtection"))


def protection_message(cluster: str) -> str:
    return f"deletion protection is on for {cluster}; run 'capellactl cluster protect {cluster} --off' first"
