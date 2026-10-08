"""Scale-in and scale-down guards (CAP-016, CAP-017 AC6; 00-architecture.md section 7.2).

A change that lowers the data service's capacity (fewer data nodes, less RAM per data node) or removes a service
group is checked before it is planned:

| Guard | Rule |
|---|---|
| Data service | at least one group keeps `data` (never overridable) |
| Other services | removing the last nodes of index/query/search/analytics/eventing needs --allow-service-removal |
| Group removal | removing a whole service group needs --allow-service-group-removal |
| Memory | `allocated = total − free` must fit `projected = total × new data memory / old data memory` |
| Replicas | every bucket's `replicas ≤ new data nodes − 1` |

Memory needs `GET …/stats`; when it cannot be read the change is blocked unless --skip-capacity-check.
"""

from __future__ import annotations

from typing import Any

from capellactl.api import endpoints as ep
from capellactl.api.errors import CapellaApiError
from capellactl.engine.context import RunContext
from capellactl.engine.normalize import group_key

OTHER_SERVICES = ("index", "query", "search", "analytics", "eventing")


def _data_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [g for g in groups if "data" in (g.get("services") or [])]


def data_nodes(groups: list[dict[str, Any]]) -> int:
    return sum(int(g.get("numOfNodes") or 0) for g in _data_groups(groups))


def data_memory(groups: list[dict[str, Any]]) -> int:
    """Data nodes × RAM per node (GB): the data service's share the memory guard scales by."""
    return sum(int(g.get("numOfNodes") or 0) * int(((g.get("node") or {}).get("compute") or {}).get("ram") or 0)
               for g in _data_groups(groups))


def after_change(observed: list[dict[str, Any]], desired: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The service groups once the change is applied (desired values over observed, by group key)."""
    if desired is None:
        return observed
    by_key = {group_key(g): g for g in observed}
    out = []
    for d in desired:
        o = by_key.get(group_key(d), {})
        merged = {**o, **d, "node": {**(o.get("node") or {}), **(d.get("node") or {}),
                                     "compute": {**((o.get("node") or {}).get("compute") or {}),
                                                 **((d.get("node") or {}).get("compute") or {})}}}
        out.append(merged)
    return out


def _mb(n: float) -> str:
    return f"{round(n):,}"


def reduces_capacity(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> bool:
    removed = {group_key(g) for g in old} - {group_key(g) for g in new}
    return bool(removed) or data_nodes(new) < data_nodes(old) or data_memory(new) < data_memory(old)


def check(ctx: RunContext, project_id: str, cluster_id: str, old: list[dict[str, Any]],
          new: list[dict[str, Any]]) -> tuple[list[str], str | None]:
    """(blocked reasons, `checks: …` remark) for a change from `old` to `new` service groups."""
    blocked: list[str] = []
    n, m = data_nodes(old), data_nodes(new)
    if m == 0:
        return ["scale-in blocked: removing the last group that runs data"], None
    old_keys, new_keys = {group_key(g): g for g in old}, {group_key(g) for g in new}
    removed = [k for k in old_keys if k not in new_keys]
    lost = [s for s in OTHER_SERVICES if any(s in (g.get("services") or []) for g in old)
            and not any(s in (g.get("services") or []) for g in new)]
    for k in removed:
        services = [s for s in lost if s in (old_keys[k].get("services") or [])]
        need = (["--allow-service-removal"] if services and not ctx.allow_service_removal else []) + \
               (["--allow-service-group-removal"] if not ctx.allow_service_group_removal else [])
        if need:
            what = f"removes the last {', '.join(services)} nodes" if services else "removes a whole service group"
            blocked.append(f"removing serviceGroups[{k}] {what}; pass {' '.join(need)}")
    if not removed and lost and not ctx.allow_service_removal:
        blocked.append(f"scale-in blocked: the last {', '.join(lost)} nodes would be removed; pass "
                       "--allow-service-removal")
    if blocked:
        return blocked, None
    if data_memory(new) >= data_memory(old) and m >= n:
        return [], None  # the data service does not shrink: no capacity checks needed
    checks: list[str] = []
    change = f"{n} → {m} nodes" if m != n else (
        f"{data_memory(old) // max(n, 1)} → {data_memory(new) // max(m, 1)} GB per node")
    try:
        stats = ep.get_cluster_stats(ctx.client, project_id, cluster_id)
    except CapellaApiError:
        stats = None
    if stats is None:
        if not ctx.skip_capacity_check:
            return ["cannot verify capacity (stats unavailable); pass --skip-capacity-check to proceed at your own "
                    "risk"], None
        checks.append("memory not checked (--skip-capacity-check)")
    else:
        total, free = float(stats.get("totalMemoryInMb") or 0), float(stats.get("freeMemoryInMb") or 0)
        allocated = total - free
        projected = total * data_memory(new) / max(data_memory(old), 1)
        if allocated > projected:
            blocked.append(f"scale-in blocked: buckets allocate {_mb(allocated)} MB but data service would have "
                           f"~{_mb(projected)} MB after scale-in ({change})")
        else:
            checks.append(f"memory ok ({_mb(allocated)} / ~{_mb(projected)} MB)")
    buckets = ep.list_buckets(ctx.client, project_id, cluster_id)
    worst = max(buckets, key=lambda b: int(b.get("replicas") or 0), default=None)
    replicas = int(worst.get("replicas") or 0) if worst else 0
    if worst is not None and replicas > m - 1:
        blocked.append(f"scale-in blocked: bucket '{worst.get('name')}' has {replicas} replica"
                       f"{'s' if replicas != 1 else ''} and needs at least {replicas + 1} data nodes")
    else:
        checks.append(f"replicas ok (max {replicas}, needs {replicas + 1} data node{'s' if replicas else ''})")
    return blocked, None if blocked else "checks: " + " · ".join(checks)
