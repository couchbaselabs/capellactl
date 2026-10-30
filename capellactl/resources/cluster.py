"""Cluster reconciler: create (CAP-011), edit settings (CAP-012), scale out and up (CAP-015/017).

Scale-in and RAM decreases pass the capacity checks of resources/scaling.py (CAP-016, CAP-017 AC6); a disk never shrinks.
"""

from __future__ import annotations

from typing import Any

from capellactl.api import endpoints as ep
from capellactl.api.errors import NotFound
from capellactl.engine.context import RunContext
from capellactl.engine.normalize import deep_merge, field_changes, group_key
from capellactl.engine.waiter import TRANSITIONAL, wait_for_cluster
from capellactl.resources.base import (
    RENAMED_NOTE,
    Action,
    ActionType,
    Change,
    Observed,
    PlanError,
    Reconciler,
)

CREATE_FIELDS = ["name", "description", "configurationType", "cloudProvider", "couchbaseServer", "serviceGroups",
                 "availability", "support", "zones", "cmekId", "enablePrivateDNSResolution"]
IMMUTABLE = ["configurationType", "cloudProvider", "availability", "zones", "cmekId", "enablePrivateDNSResolution",
             "couchbaseServer"]
NOT_API = {"id", "tier", "deletionProtection", "allowAnyIp", "allowedCidrs", "hibernation", "backupSchedule", "buckets",
           "databaseCredentials"}
FREE_SERVICES = "data,index,query,search"


def is_free(body: dict[str, Any]) -> bool:
    """Capella reports free-tier clusters with support.plan 'free'."""
    return str((body.get("support") or {}).get("plan", "")).lower() == "free"
GROUP_FIELDS = ("node", "numOfNodes", "services")
OFF_STATES = ("turnedOff", "turningOff")
FAILED = {"deploymentFailed", "scaleFailed", "upgradeFailed", "rebalanceFailed", "peeringFailed", "destroyFailed",
          "turningOffFailed", "turningOnFailed"}


def _size(group: dict[str, Any]) -> str:
    node = group.get("node") or {}
    comp, disk = node.get("compute") or {}, node.get("disk") or {}
    s = f"{group.get('numOfNodes')} × {comp.get('cpu')} vCPU/{comp.get('ram')} GB"
    if disk.get("type"):
        s += f" {disk.get('type')}"
    if disk.get("storage"):
        s += f" {disk.get('storage')} GB"
    return s


def create_summary(d: dict[str, Any]) -> str:
    cp = d.get("cloudProvider") or {}
    if d.get("tier") == "free":
        return f"free tier · {cp.get('type')} {cp.get('region')} · 1 node · {FREE_SERVICES}"
    parts = [f"{cp.get('type')} {cp.get('region')}"]
    parts.append("multi-AZ" if (d.get("availability") or {}).get("type") == "multi" else "single-AZ")
    if d.get("configurationType") == "singleNode":
        parts.append("single node")
    groups = d.get("serviceGroups") or []
    if len(groups) > 1:  # one plan line per group follows (create_group_lines)
        parts.append(f"{len(groups)} service groups · {sum(int(g.get('numOfNodes') or 0) for g in groups)} nodes")
    for g in groups if len(groups) == 1 else []:
        node = g.get("node") or {}
        comp = node.get("compute") or {}
        parts.append(f"{g.get('numOfNodes')} × {comp.get('cpu')} vCPU/{comp.get('ram')} GB")
        parts.append(",".join(sorted(g.get("services") or [])))
    parts.append(str((d.get("support") or {}).get("plan", "")).lower())
    return " · ".join(p for p in parts if p)


def create_group_lines(d: dict[str, Any]) -> list[str]:
    """Plan lines under a new multi-dimensional cluster: each group expanded with its disk (CAP-051)."""
    groups = d.get("serviceGroups") or []
    if len(groups) < 2:
        return []
    width = max(len(group_key(g)) for g in groups)
    return [f"+ serviceGroups[{group_key(g)}]{' ' * (width - len(group_key(g)))}  {_size(g)}" for g in groups]


def _version_matches(desired: str | None, observed: str | None) -> bool:
    if not desired:
        return True
    return bool(observed) and (observed == desired or str(observed).startswith(f"{desired}."))


# Capella has no lighter call for description/support changes: the full cluster PUT starts a cluster job that the
# Capella UI lists as "scale" ("Deploying database-wide assets"), even though no node changes (seen 2026-10-07).
SETTINGS_ONLY_NOTE = 'note: Capella runs a cluster update job for this (shown as "scale" in the Capella UI); nodes do not change'


def fixed_size_disk(provider: Any, disk_type: Any) -> bool:
    """Azure premium disks (P6 … P60) have a size and IOPS set by their type: Capella refuses `storage`/`iops` for
    them ("Cannot specify disk size or IOPS for disk type P6"); only Ultra takes them (spec: DiskAzure)."""
    return bool(provider == "azure" and disk_type != "Ultra")


def _api_group(g: dict[str, Any], provider: Any = None) -> dict[str, Any]:
    out = {k: g[k] for k in GROUP_FIELDS if k in g}
    disk = (out.get("node") or {}).get("disk")
    if isinstance(disk, dict) and fixed_size_disk(provider, disk.get("type")):
        out["node"] = {**out["node"], "disk": {k: v for k, v in disk.items() if k not in ("storage", "iops")}}
    return out


def build_update_body(observed: dict[str, Any], desired: dict[str, Any], rename: bool) -> dict[str, Any]:
    """Full PUT body: observed overlaid with desired (00-architecture.md section 6.4)."""
    desired_groups = {group_key(g): g for g in desired.get("serviceGroups") or []}
    provider = (observed.get("cloudProvider") or desired.get("cloudProvider") or {}).get("type")
    groups: list[dict[str, Any]] = []
    seen = set()
    for og in observed.get("serviceGroups") or []:
        k = group_key(og)
        seen.add(k)
        if k in desired_groups:
            groups.append(_api_group(deep_merge(_api_group(og), _api_group(desired_groups[k])), provider))
        elif desired.get("serviceGroups") is None:
            groups.append(_api_group(og, provider))
        # groups removed from the file are dropped (only reachable once scale-in is allowed)
    for k, dg in desired_groups.items():
        if k not in seen:
            groups.append(_api_group(dg, provider))
    return {
        "name": desired["name"] if rename else observed.get("name", desired["name"]),
        "description": desired["description"] if "description" in desired else observed.get("description", ""),
        "support": deep_merge(observed.get("support") or {}, desired.get("support") or {}),
        "serviceGroups": groups,
    }


def service_group_changes(desired: dict[str, Any], observed: dict[str, Any]) -> tuple[list[Change], list[str], set[str]]:
    """Changes, blocked reasons, labels ('scale out', 'scale up', 'scale in')."""
    changes: list[Change] = []
    blocked: list[str] = []
    labels: set[str] = set()
    if "serviceGroups" not in desired:
        return changes, blocked, labels
    d_groups = {group_key(g): g for g in desired.get("serviceGroups") or []}
    o_groups = {group_key(g): g for g in observed.get("serviceGroups") or []}
    for k, dg in d_groups.items():
        if k not in o_groups:
            changes.append(Change(f"serviceGroups[{k}]", None, _size(dg)))
            labels.add("scale out")
            continue
        og = o_groups[k]
        for c in field_changes(_api_group(dg), og, prefix=f"serviceGroups[{k}]", skip={"services"}):
            changes.append(c)
            if c.path.endswith("numOfNodes"):
                if isinstance(c.before, int) and isinstance(c.after, int) and c.after < c.before:
                    labels.add("scale in")  # capacity checks: resources/scaling.py (CAP-016)
                else:
                    labels.add("scale out")
            elif c.path.endswith("disk.storage") and isinstance(c.before, int) and isinstance(c.after, int) \
                    and c.after < c.before:
                blocked.append(f"{c.path}: {c.before} → {c.after} GB  disk size cannot be reduced")
            elif c.path.endswith("compute.ram") and isinstance(c.before, int) and isinstance(c.after, int) \
                    and c.after < c.before:
                labels.add("scale down")  # memory guard: resources/scaling.py (CAP-017 AC6)
            else:
                labels.add("scale up")
    for k in o_groups:
        if k not in d_groups:
            changes.append(Change(f"serviceGroups[{k}]", _size(o_groups[k]), None))
            labels.add("scale in")
    return changes, blocked, labels


class ClusterReconciler(Reconciler):
    kind = "cluster"
    story = "CAP-011"
    listed_when_asked = True  # drift lists undeclared clusters; --prune never deletes them (CAP-031 AC3)

    def __init__(self, children: list[Reconciler] | None = None) -> None:
        super().__init__(children)
        self._seen: dict[str, list[Observed]] = {}

    def desired_items(self, parent_desired: Any) -> list[Any]:
        return list(parent_desired.get("_clusters") or [])

    def key(self, desired: Any, parent: Action | None) -> str:
        return str(desired["name"])

    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        assert parent is not None and parent.id is not None
        found = [Observed(str(c["id"]), c) for c in ep.list_clusters(ctx.client, parent.id)]
        # Free-tier clusters are recorded with their id; read any that the list does not include.
        listed = {o.id for o in found}
        for d in (parent.desired or {}).get("_clusters") or []:
            if d.get("tier") == "free" and d.get("id") and d["id"] not in listed:
                try:
                    body, _ = ep.get_free_cluster(ctx.client, parent.id, str(d["id"]))
                    found.append(Observed(str(d["id"]), body))
                except NotFound:
                    pass
        self._seen[parent.id] = found
        return found

    def _rename_hint(self, desired: dict[str, Any], parent: Action | None) -> str | None:
        """CAP-012 AC6: a new name next to an undeclared existing cluster is probably a rename."""
        if parent is None or parent.id is None or desired.get("id"):
            return None
        declared = {c.get("name") for c in (parent.desired or {}).get("_clusters") or []}
        others = [o for o in self._seen.get(parent.id, []) if o.body.get("name") not in declared]
        if len(others) != 1:
            return None
        old = others[0].body.get("name")
        return (f"(warning: no cluster named {desired['name']}; did you mean to rename {old}? "
                f"pin id: {others[0].id} to rename)")

    def match(self, desired: Any, observed: list[Observed]) -> list[Observed]:
        pinned = desired.get("id")
        if pinned:
            found = [o for o in observed if o.id == pinned]
            if not found:
                raise PlanError(f"cluster {pinned} not found")
            return found
        return [o for o in observed if o.body.get("name") == desired["name"]]

    def after_children_note(self) -> str:
        return "(after cluster is healthy)"

    def unmanaged_label(self, observed: Observed, parent: Action | None) -> str:
        return f"cluster {observed.body.get('name', observed.id)}"

    def _changes(self, desired: dict[str, Any], body: dict[str, Any]) -> tuple[list[Change], list[Change], list[str], set[str]]:
        immutable: list[Change] = []
        for f in IMMUTABLE:
            if f not in desired:
                continue
            if f == "couchbaseServer":
                dv = (desired.get(f) or {}).get("version")
                ov = (body.get(f) or {}).get("version")
                if not _version_matches(dv, ov):
                    immutable.append(Change("couchbaseServer.version", ov, dv))
                continue
            if f == "zones" and "zones" not in body:
                continue  # not returned by GET
            immutable += field_changes({f: desired[f]}, body)
        skip = set(IMMUTABLE) | NOT_API | {"serviceGroups"}
        if not desired.get("id"):
            skip.add("name")
        updatable = field_changes(desired, body, skip=skip)
        sg_changes, sg_blocked, labels = service_group_changes(desired, body)
        return immutable, updatable + sg_changes, sg_blocked, labels

    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        key = self.key(desired, parent)
        if observed is None:
            action = Action(self.kind, key, ActionType.CREATE, self, desired=desired, parent=parent,
                            summary=create_summary(desired),
                            data={"state": None, "free": desired.get("tier") == "free"})
            action.remarks += create_group_lines(desired)
            hint = self._rename_hint(desired, parent)
            if hint:
                action.notes.append(hint)
            return action
        body = observed.body
        state = str(body.get("currentState", "unknown"))
        free = desired.get("tier") == "free"
        a = Action(self.kind, key, ActionType.NOOP, self, desired=desired, observed=observed, parent=parent,
                   data={"state": state, "free": free})
        if free != is_free(body):
            a.type, a.topic = ActionType.BLOCKED, "config"
            a.reason = (f"{key} is a free-tier cluster in Capella; capella.yaml should say tier: free "
                        "(run 'capellactl sync')" if is_free(body) else
                        f"{key} is a provisioned cluster in Capella; it cannot become a free-tier cluster")
            return a
        immutable, changes, sg_blocked, labels = self._changes(desired, body)
        if state == "deploymentFailed":
            a.type, a.topic = ActionType.BLOCKED, "safety"
            a.reason = f"in deploymentFailed; delete it (capellactl cluster delete {key}) and re-run apply"
            return a
        if state in FAILED or state in ("degraded", "offline"):
            a.type, a.topic = ActionType.BLOCKED, "safety"
            a.reason = f"cluster is {state}; check the Capella UI activity log before changing it"
            return a
        if immutable:
            a.type, a.changes, a.topic = ActionType.BLOCKED, immutable, "idempotency"
            a.reason = "immutable: " + ", ".join(c.path for c in immutable) + " (requires a new cluster)"
            return a
        checks = None
        if not sg_blocked and labels & {"scale in", "scale down"} and state not in OFF_STATES and parent is not None:
            from capellactl.resources import scaling

            old = list(body.get("serviceGroups") or [])
            new = scaling.after_change(old, desired.get("serviceGroups"))
            if scaling.reduces_capacity(old, new):
                assert parent.id is not None and observed.id is not None
                sg_blocked, checks = scaling.check(ctx, parent.id, observed.id, old, new)
        if sg_blocked:
            a.type, a.changes, a.topic = ActionType.BLOCKED, changes, "scaling"
            a.reason = "; ".join(sg_blocked)
            return a
        if state in OFF_STATES and ctx.power_on:  # apply --power-on (CAP-019 AC6)
            a.type, a.changes = ActionType.UPDATE, [Change("power", "off", "on"), *changes]
            a.label = " / ".join(["power on", *sorted(labels)])
            a.data["power_on"] = True
            a.data["more"] = bool(changes)
            return a
        if changes and state in OFF_STATES:
            a.type, a.changes, a.topic = ActionType.BLOCKED, changes, "hibernation"
            what = "scaling" if labels else "changing it"
            a.reason = (f"turned off; power it on before {what} (capellactl cluster power {key} --on, "
                        "or apply --power-on)")
            return a
        if changes:
            a.type, a.changes = ActionType.UPDATE, changes
            a.label = " / ".join(sorted(labels)) if labels else None
            if any(c.path == "name" for c in changes):
                a.notes.append(RENAMED_NOTE)
            if not any(c.path.startswith("serviceGroups") for c in changes) and not free:
                a.data["settings_only"] = True
                a.remarks.append(SETTINGS_ONLY_NOTE)
            if checks:
                a.remarks.append(checks)
        return a

    # --------------------------------------------------------------- apply
    def _project_id(self, action: Action) -> str:
        p = action.ancestor("project")
        assert p is not None and p.id is not None
        return p.id

    def delete_action(self, ctx: RunContext, observed: Observed, parent: Action | None) -> Action:
        """`destroy` (CAP-030): the cluster, after everything below it; waits until it is gone."""
        return Action(self.kind, str(observed.body.get("name")), ActionType.DELETE, self,
                      desired={"name": observed.body.get("name")}, observed=observed, parent=parent,
                      data={"state": observed.body.get("currentState"), "free": is_free(observed.body)})

    def apply(self, ctx: RunContext, action: Action) -> None:
        d = action.desired
        pid = self._project_id(action)
        if action.type is ActionType.DELETE:
            assert action.observed is not None and action.observed.id is not None
            if action.data.get("free"):
                ep.delete_free_cluster(ctx.client, pid, action.observed.id)
            else:
                ep.delete_cluster(ctx.client, pid, action.observed.id,
                                  retain_snapshot_backups=not action.data.get("discard_snapshots"))
            action.data["sent"] = True
            return
        if action.type is ActionType.CREATE and action.data.get("free"):
            body = {k: d[k] for k in ("name", "description", "cloudProvider") if k in d}
            action.created_id = ep.create_free_cluster(ctx.client, pid, body)
            action.data["state"] = "deploying"
            action.data["sent"] = True
            return
        if action.type is ActionType.UPDATE and action.data.get("power_on"):
            assert action.observed is not None and action.observed.id is not None
            if action.data.get("state") == "turningOff":
                self._wait(ctx, action, "power_off")
            if action.data.get("free"):
                ep.turn_free_cluster_on(ctx.client, pid, action.observed.id)
            else:
                ep.turn_cluster_on(ctx.client, pid, action.observed.id)
            action.data["state"] = "turningOn"
            self._wait(ctx, action, "power_on")
            if not action.data.get("more"):
                action.data["sent"] = False
                return
        if action.type is ActionType.UPDATE and action.data.get("free"):
            assert action.observed is not None and action.observed.id is not None
            if action.data.get("state") != "healthy":
                self._wait(ctx, action, "ready")
            current, etag = ep.get_free_cluster(ctx.client, pid, action.observed.id)
            body = {"name": d["name"] if d.get("id") else current.get("name", d["name"]),
                    "description": d["description"] if "description" in d else current.get("description", "")}
            ep.update_free_cluster(ctx.client, pid, action.observed.id, body, if_match=etag)
            action.data["sent"] = False  # name/description only: nothing to wait for
            return
        if action.type is ActionType.CREATE:
            body = {k: d[k] for k in CREATE_FIELDS if k in d}
            provider = (d.get("cloudProvider") or {}).get("type")
            body["serviceGroups"] = [_api_group(g, provider) for g in d.get("serviceGroups") or []]
            action.created_id = ep.create_cluster(ctx.client, pid, body)
            action.data["state"] = "deploying"
            action.data["sent"] = True
            return
        if action.type is ActionType.UPDATE:
            assert action.observed is not None and action.observed.id is not None
            cid = action.observed.id
            if action.data.get("state") != "healthy":
                self._wait(ctx, action, "ready")
            current, etag = ep.get_cluster(ctx.client, pid, cid)
            immutable, changes, blocked, _ = self._changes(d, current)
            if not changes:
                action.data["sent"] = False
                return
            body = build_update_body(current, d, rename=bool(d.get("id")))
            ep.update_cluster(ctx.client, pid, cid, body, if_match=etag)
            action.data["state"] = "scaling"
            action.data["sent"] = True

    def _wait(self, ctx: RunContext, action: Action, op: Any) -> None:
        pid = self._project_id(action)
        cid = action.id
        assert cid is not None

        inline = ctx.progress_inline

        def on_state(state: str, elapsed: float) -> None:
            from capellactl.engine.clock import format_duration

            shown = (f"applying the change (Capella: {state})"
                     if action.data.get("settings_only") and state in TRANSITIONAL else state)
            line = f"  cluster {action.key}: {shown} ({format_duration(elapsed)})"
            if inline and state in TRANSITIONAL:
                inline(line + " ")  # dots follow on the same line
            else:
                ctx.progress(line)

        getter = ep.get_free_cluster if action.data.get("free") else None
        state = wait_for_cluster(ctx.client, pid, cid, op, ctx.timeout, ctx.clock, on_state, name=action.key,
                                 getter=getter, on_tick=(lambda: inline(".")) if inline else None)
        action.data["state"] = state

    def wait(self, ctx: RunContext, action: Action) -> None:
        if not action.data.get("sent"):
            return
        op = {ActionType.CREATE: "create", ActionType.DELETE: "delete"}.get(action.type, "update")
        self._wait(ctx, action, op)

    def child_block_reason(self, ctx: RunContext, action: Action, child_kind: str) -> str | None:
        """Nothing below a turned-off cluster can change, except its schedule (CAP-019 AC6, CAP-020 AC8)."""
        if action.data.get("state") not in OFF_STATES or ctx.power_on or child_kind == "schedule":
            return None
        reason = f"cluster is turned off; run 'capellactl cluster power {action.key} --on' or pass --power-on"
        if "next_on" not in action.data:
            action.data["next_on"] = self._next_on(ctx, action)
        if action.data["next_on"]:
            reason += f" (the schedule turns it on at {action.data['next_on']})"
        return reason

    def _next_on(self, ctx: RunContext, action: Action) -> str | None:
        from capellactl.resources.schedule import next_on_text

        try:
            body, _ = ep.get_schedule(ctx.client, self._project_id(action), str(action.id))
        except Exception:  # noqa: BLE001 - informational only
            return None
        if body.get("activationStatus") == "paused":
            return None
        return next_on_text(body, ctx.clock.now())

    def ensure_ready(self, ctx: RunContext, action: Action, child: Action | None = None) -> bool:
        state = action.data.get("state")
        if state == "healthy":
            return True
        if state == "turnedOff" and child is not None and child.kind == "schedule":
            return True  # a schedule can be changed while the cluster is off (CAP-020 AC8)
        if state in TRANSITIONAL or state is None:
            if ctx.no_wait:
                return False
            if action.id is None:
                return False
            self._wait(ctx, action, "ready")
            return action.data.get("state") == "healthy"
        return False
