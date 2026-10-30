"""Allowed CIDRs (IP allowlist) reconciler (CAP-022).

An entry is identified by its canonical CIDR (a bare IP is /32). The API has no update, so a change to
`comment` or `expiresAt` is a REPLACE: create the new entry first, then delete the old one; when Capella
rejects the duplicate (409), delete first and create again, with a short loss of access.

Entries in Capella that the file does not declare are listed as unmanaged by `plan` and deleted only by
`apply --prune`.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any

from capellactl.api import endpoints as ep
from capellactl.api.errors import Conflict, NotFound
from capellactl.config.crossref import (
    ANY_IP,
    normalize_cidr,
)
from capellactl.engine.context import RunContext
from capellactl.resources.base import Action, ActionType, Change, Observed, Reconciler

REPLACE_NOTE = "(replace: API has no update)"


def canonical(cidr: str) -> str:
    """Canonical form for matching; Capella's own values are read leniently."""
    try:
        return normalize_cidr(cidr)
    except ValueError:
        return cidr.strip()


def parse_time(value: Any) -> datetime | None:
    """RFC 3339 → aware datetime (None when absent or unreadable)."""
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def is_expired(expires_at: Any, now: datetime | None = None) -> bool:
    t = parse_time(expires_at)
    return t is not None and t <= (now or datetime.now(timezone.utc))


def create_body(desired: dict[str, Any]) -> dict[str, Any]:
    """{cidr, comment[, expiresAt]}; empty fields are omitted (AC1)."""
    body: dict[str, Any] = {"cidr": canonical(str(desired["cidr"]))}
    if desired.get("comment"):
        body["comment"] = desired["comment"]
    if desired.get("expiresAt"):
        body["expiresAt"] = desired["expiresAt"]
    return body


def cidr_changes(desired: dict[str, Any], observed: dict[str, Any]) -> list[Change]:
    """comment and expiresAt as the file has them; omitted comment = none, omitted expiresAt = permanent."""
    changes = []
    d_comment, o_comment = desired.get("comment") or "", observed.get("comment") or ""
    if d_comment != o_comment:
        changes.append(Change("comment", o_comment or None, d_comment or None))
    d_exp, o_exp = desired.get("expiresAt"), observed.get("expiresAt")
    if parse_time(d_exp) != parse_time(o_exp):
        changes.append(Change("expiresAt", o_exp or None, d_exp or None))
    return changes


def summary(desired: dict[str, Any]) -> str:
    parts = []
    if desired.get("comment"):
        parts.append(f'"{desired["comment"]}"')
    parts.append(f"expires {desired['expiresAt']}" if desired.get("expiresAt") else "permanent")
    return " · ".join(parts)


class AllowedCidrReconciler(Reconciler):
    kind = "allowed-cidr"
    story = "CAP-022"
    prunable = True
    reports_unmanaged = True

    def desired_items(self, parent_desired: Any) -> list[Any]:
        return list(parent_desired.get("allowedCidrs") or []) if isinstance(parent_desired, dict) else []

    def key(self, desired: Any, parent: Action | None) -> str:
        cidr = canonical(str(desired["cidr"]))
        return f"{parent.key}/{cidr}" if parent else cidr

    def _ids(self, cluster: Action | None) -> tuple[str, str]:
        project = cluster.ancestor("project") if cluster is not None else None
        assert cluster is not None and cluster.id is not None and project is not None and project.id is not None
        return project.id, cluster.id

    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        return [Observed(str(c["id"]), c) for c in ep.list_allowed_cidrs(ctx.client, *self._ids(parent))]

    def match(self, desired: Any, observed: list[Observed]) -> list[Observed]:
        want = canonical(str(desired["cidr"]))
        return [o for o in observed if canonical(str(o.body.get("cidr", ""))) == want]

    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        key = self.key(desired, parent)
        cidr = canonical(str(desired["cidr"]))
        cluster = parent.key if parent else "CLUSTER"
        confirmed = bool(parent is not None and isinstance(parent.desired, dict) and parent.desired.get("allowAnyIp"))
        if cidr in ANY_IP and confirmed:
            ctx.warn(f"allowed CIDR {cidr} on {cluster} lets any IP address connect (allowAnyIp: true)",
                     "Keep it only if the cluster must be reachable from anywhere; otherwise run 'capellactl cidr "
                     f"delete {cluster} {cidr}'.")
        if observed is None:
            if is_expired(desired.get("expiresAt"), ctx.clock.now()):
                return Action(self.kind, key, ActionType.NOOP, self, desired=desired, parent=parent,
                              notes=["(expiresAt is in the past; Capella removed it, not re-created)"])
            if cidr in ANY_IP and not confirmed:  # CAP-022 AC5: never open a cluster to every address by accident
                return Action(self.kind, key, ActionType.BLOCKED, self, desired=desired, parent=parent, topic="safety",
                              reason=f"{cidr} would let every IP address connect; to create it, run 'capellactl cidr "
                                     f"create {cluster} {cidr} --allow-any-ip'")
            return Action(self.kind, key, ActionType.CREATE, self, desired=desired, parent=parent,
                          summary=summary(desired))
        changes = cidr_changes(desired, observed.body)
        if not changes:
            return Action(self.kind, key, ActionType.NOOP, self, desired=desired, observed=observed, parent=parent)
        return Action(self.kind, key, ActionType.REPLACE, self, desired=desired, observed=observed, parent=parent,
                      changes=changes, notes=[REPLACE_NOTE])

    def unmanaged_label(self, observed: Observed, parent: Action | None) -> str:
        cidr = canonical(str(observed.body.get("cidr", "")))
        label = f"{self.kind} {parent.key}/{cidr}" if parent else f"{self.kind} {cidr}"
        if observed.body.get("comment"):
            label += f'  "{observed.body["comment"]}"'
        return label

    def delete_action(self, ctx: RunContext, observed: Observed, parent: Action | None) -> Action:
        cidr = canonical(str(observed.body.get("cidr", "")))
        key = f"{parent.key}/{cidr}" if parent else cidr
        return Action(self.kind, key, ActionType.DELETE, self, desired={"cidr": cidr}, observed=observed, parent=parent)

    def apply(self, ctx: RunContext, action: Action) -> None:
        pid, cid = self._ids(action.parent)
        if action.type is ActionType.CREATE:
            action.created_id = ep.create_allowed_cidr(ctx.client, pid, cid, create_body(action.desired))
            return
        assert action.observed is not None and action.observed.id is not None
        old = action.observed.id
        if action.type is ActionType.DELETE:
            with contextlib.suppress(NotFound):  # already gone (expired or deleted): the goal is reached
                ep.delete_allowed_cidr(ctx.client, pid, cid, old)
            return
        if action.type is ActionType.REPLACE:
            body = create_body(action.desired)
            try:
                new = ep.create_allowed_cidr(ctx.client, pid, cid, body)
            except Conflict:  # Capella does not accept the same CIDR twice: delete first, then create
                ctx.warn(f"access from {body['cidr']} is briefly interrupted",
                         "None needed: Capella replaces the range, and access returns within seconds.")
                with contextlib.suppress(NotFound):
                    ep.delete_allowed_cidr(ctx.client, pid, cid, old)
                action.created_id = ep.create_allowed_cidr(ctx.client, pid, cid, body)
                return
            with contextlib.suppress(NotFound):
                ep.delete_allowed_cidr(ctx.client, pid, cid, old)
            action.created_id = new
