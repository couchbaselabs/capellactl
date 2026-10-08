"""Build a plan: desired (file) vs observed (live API) for every resource (CAP-005)."""

from __future__ import annotations

from typing import Any

from capellactl.config.loader import Config
from capellactl.engine.context import RunContext
from capellactl.resources.base import WRITE_TYPES, Action, ActionType, Plan, Reconciler


def normalize_targets(targets: list[str] | None) -> list[tuple[str, str]] | None:
    """'cluster/nova-dev-01' → ('cluster', 'nova-dev-01'); 'bucket/nova-dev-01/orders' → ('bucket', 'nova-dev-01/orders')."""
    if not targets:
        return None
    out = []
    for t in targets:
        t = t.strip().strip("/")
        if "/" not in t:
            raise ValueError(f"invalid --target '{t}': use KIND/NAME, for example cluster/nova-dev-01")
        kind, path = t.split("/", 1)
        out.append((kind, path))
    return out


def _target_match(kind: str, key: str, targets: list[tuple[str, str]] | None, alt: str | None = None) -> str:
    """'self' if targeted, 'ancestor' if a target is below it, '' otherwise.

    `alt` is the project-qualified key of a cluster ('PROJECT/NAME'), accepted when a name repeats.
    """
    if not targets:
        return "self"
    rel = ""
    for t_kind, t_path in targets:
        if t_kind == kind and (t_path == key or (alt is not None and t_path == alt)):
            return "self"
        if t_kind == kind and alt is not None and t_path.count("/") == alt.count("/") and t_path != alt:
            continue  # qualified target for the same name in another project
        below = t_path.startswith(key + "/") or (alt is not None and t_path.startswith(alt + "/"))
        same_key_child = t_kind != kind and t_path in (key, alt)  # e.g. schedule/NAME: one per cluster, same key
        if kind == "project" or below or same_key_child:
            rel = "ancestor"
    return rel


def _block_by_ancestor(ctx: RunContext, action: Action) -> None:
    """A write below a resource that cannot take it now (for example a turned-off cluster) is BLOCKED."""
    if action.type not in WRITE_TYPES:
        return
    anc = action.parent
    while anc is not None:
        reason = anc.reconciler.child_block_reason(ctx, anc, action.kind)
        if reason:
            action.type, action.reason, action.topic = ActionType.BLOCKED, reason, "hibernation"
            return
        anc = anc.parent


def build_plan(ctx: RunContext, config: Config, root: Reconciler, targets: list[str] | None = None,
               descendants: bool = True, prune: bool = False, all_unmanaged: bool = False) -> Plan:
    """`descendants=False` plans targeted resources without their children (e.g. `project update`).

    `prune=True` also plans deletes for resources of prunable kinds that exist in Capella but are no
    longer declared in the file (`apply --prune`); without it, removing an item from the file changes nothing.
    `all_unmanaged=True` (`drift`) lists every undeclared resource of a prunable kind, and undeclared clusters.
    """
    actions: list[Action] = []
    unmanaged: list[str] = []
    tgts = normalize_targets(targets)

    def walk(rec: Reconciler, parent_desired: Any, parent: Action | None, parent_target: str) -> None:
        desired_list = rec.desired_items(parent_desired)
        lists = rec.reports_unmanaged or (all_unmanaged and rec.prunable) or \
            (rec.listed_when_asked and (all_unmanaged or prune))
        looks_for_undeclared = not rec.grouped and ((prune and rec.prunable) or lists)
        if not desired_list and not looks_for_undeclared:
            return
        if rec.grouped:
            action = rec.diff(ctx, desired_list, None, parent)
            if parent_target in ("self", "descendant") or _target_match(rec.kind, action.key, tgts) == "self":
                actions.append(action)
            return

        parent_exists = parent is None or parent.reconciler.ready_for_children(parent)
        observed = rec.observe(ctx, parent) if parent_exists else []
        matched: set[int] = set()
        for d in desired_list:
            key = rec.key(d, parent)
            alt = f"{parent.key}/{key}" if rec.kind == "cluster" and parent is not None else None
            if parent_target in ("self", "descendant"):
                rel = "descendant"
            else:
                rel = _target_match(rec.kind, key, tgts, alt)
            if not rel:
                continue
            matches = rec.match(d, observed)
            matched.update(id(m) for m in matches)
            if len(matches) > 1:
                ids = ", ".join(str(m.id) for m in matches)
                where = " under project:" if rec.kind == "project" else ""
                action = Action(
                    rec.kind, key, ActionType.BLOCKED, rec, desired=d, parent=parent,
                    reason=f"{len(matches)} {rec.kind}s share this name (ids: {ids}); add id:{where} to choose one",
                    topic="idempotency",
                )
            else:
                action = rec.diff(ctx, d, matches[0] if matches else None, parent)
            if parent is not None and not parent_exists and action.type is ActionType.CREATE:
                action.notes.append(parent.reconciler.after_children_note())
            _block_by_ancestor(ctx, action)
            if rel == "ancestor" and action.type is not ActionType.CREATE:
                action.hidden = True  # context only: parents are looked up, not changed
            actions.append(action)
            if rel == "self" and tgts and not descendants:
                continue
            if action.type is ActionType.BLOCKED and action.observed is None:
                continue  # nothing exists below a resource that is blocked before it is created
            for child in rec.children:
                walk(child, d, action, rel)
        if not tgts or parent_target in ("self", "descendant"):
            undeclared = [o for o in observed if id(o) not in matched and rec.manages(o)]
            if prune and rec.prunable:
                for o in undeclared:
                    deletion = rec.delete_action(ctx, o, parent)
                    _block_by_ancestor(ctx, deletion)
                    actions.append(deletion)
            elif lists:
                note = f"  (not pruned: {rec.kind}s are never pruned)" if not rec.prunable else ""
                unmanaged.extend(rec.unmanaged_label(o, parent) + note for o in undeclared)

    walk(root, config, None, "")
    return Plan(_by_kind(actions), unmanaged)


# Within one cluster, every resource of a kind comes before the next kind (CAP-030 AC1): all buckets, then all
# scopes, then all collections, so apply reads top-down and destroy (the reverse) bottom-up. Dependencies still hold:
# each kind ranks after its parent's.
KIND_ORDER = ("project", "cluster", "deletion-protection", "schedule", "allowed-cidr", "bucket", "scope", "collection",
              "credential")


def _by_kind(actions: list[Action]) -> list[Action]:
    def owner(a: Action, kind: str) -> Action | None:
        return a if a.kind == kind else a.ancestor(kind)

    first: dict[int, int] = {}
    for i, a in enumerate(actions):
        for kind in ("project", "cluster"):
            o = owner(a, kind)
            if o is not None:
                first.setdefault(id(o), i)

    def key(item: tuple[int, Action]) -> tuple[int, int, int, int]:
        i, a = item
        p, c = owner(a, "project"), owner(a, "cluster")
        rank = KIND_ORDER.index(a.kind) if a.kind in KIND_ORDER else len(KIND_ORDER)
        return (first.get(id(p), i) if p else i, first.get(id(c), -1) if c else -1, rank, i)

    return [a for _, a in sorted(enumerate(actions), key=key)]
