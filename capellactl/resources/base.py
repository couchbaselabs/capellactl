"""Reconciler contract and plan data types (docs/release-1.0.0/00-architecture.md section 4.1)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from capellactl.engine.context import RunContext


class ActionType(str, Enum):
    NOOP = "noop"
    CREATE = "create"
    UPDATE = "update"
    REPLACE = "replace"
    DELETE = "delete"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


SYMBOL = {
    ActionType.CREATE: "+",
    ActionType.UPDATE: "~",
    ActionType.REPLACE: "±",
    ActionType.DELETE: "-",
    ActionType.NOOP: "=",
    ActionType.BLOCKED: "!",
    ActionType.DEFERRED: "…",
}
WRITE_TYPES = {ActionType.CREATE, ActionType.UPDATE, ActionType.REPLACE, ActionType.DELETE}


@dataclass
class Change:
    path: str
    before: Any
    after: Any

    def to_json(self) -> dict[str, Any]:
        return {"path": self.path, "before": self.before, "after": self.after}


@dataclass
class Observed:
    id: str | None
    body: dict[str, Any]
    etag: str | None = None


class PlanError(Exception):
    """Planning cannot continue (for example a pinned id that does not exist). Exit 1."""


# A pinned project or cluster whose name differs in Capella (CAP-048).
RENAMED_NOTE = "(renamed in Capella? 'capellactl sync' keeps the new name; apply renames it back)"


@dataclass
class Action:
    kind: str
    key: str
    type: ActionType
    reconciler: Reconciler
    desired: Any = None
    observed: Observed | None = None
    parent: Action | None = None
    changes: list[Change] = field(default_factory=list)
    reason: str | None = None
    topic: str | None = None
    summary: str | None = None
    notes: list[str] = field(default_factory=list)
    remarks: list[str] = field(default_factory=list)  # own lines under the changes ("note: …", "checks: …")
    hidden: bool = False
    label: str | None = None  # e.g. "scale out"
    # filled during apply
    created_id: str | None = None
    status: str = "pending"
    duration: float = 0.0
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str | None:
        if self.created_id:
            return self.created_id
        return self.observed.id if self.observed else None

    @property
    def exists(self) -> bool:
        """True when the resource exists in Capella now (or was created during this run)."""
        return self.id is not None and self.type is not ActionType.DELETE

    def ancestor(self, kind: str) -> Action | None:
        a = self.parent
        while a is not None:
            if a.kind == kind:
                return a
            a = a.parent
        return None

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "key": self.key,
            "action": self.type.value,
            "changes": [c.to_json() for c in self.changes],
        }
        if self.reason:
            d["reason"] = self.reason
        if self.summary:
            d["summary"] = self.summary
        if self.notes or self.remarks:
            d["notes"] = list(self.notes) + list(self.remarks)
        return d


@dataclass
class Plan:
    actions: list[Action]
    # Resources in Capella that the file does not declare, for kinds that report them (`plan` lists them;
    # only `apply --prune` deletes them). One display label each.
    unmanaged: list[str] = field(default_factory=list)

    def visible(self) -> list[Action]:
        return [a for a in self.actions if not a.hidden]

    def count(self, t: ActionType) -> int:
        return sum(1 for a in self.visible() if a.type is t)

    @property
    def has_changes(self) -> bool:
        return any(a.type in WRITE_TYPES for a in self.visible())

    @property
    def blocked(self) -> list[Action]:
        return [a for a in self.visible() if a.type is ActionType.BLOCKED]

    def summary_line(self) -> str:
        add = self.count(ActionType.CREATE) + self.count(ActionType.REPLACE)
        line = (f"Plan: {add} to add, {self.count(ActionType.UPDATE)} to change, "
                f"{self.count(ActionType.DELETE)} to delete, {self.count(ActionType.BLOCKED)} blocked.")
        deferred = self.count(ActionType.DEFERRED)
        if deferred:
            line = line[:-1] + f", {deferred} deferred."
        return line

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"actions": [a.to_json() for a in self.visible()]}
        if self.unmanaged:
            out["unmanaged"] = list(self.unmanaged)
        return out


class Reconciler(ABC):
    """One per resource kind. Implementations live in capellactl/resources/."""

    kind: str = ""
    story: str = ""
    grouped: bool = False  # True: one summarised action for all desired items (used for unsupported kinds)
    prunable: bool = False  # True: `apply --prune` deletes observed items the file no longer declares
    reports_unmanaged: bool = False  # True: `plan` lists observed items the file does not declare
    listed_when_asked: bool = False  # True: `drift` and `apply --prune` list undeclared items (never pruned)

    def __init__(self, children: list[Reconciler] | None = None) -> None:
        self.children: list[Reconciler] = list(children or [])

    # ---- desired state
    @abstractmethod
    def desired_items(self, parent_desired: Any) -> list[Any]: ...

    @abstractmethod
    def key(self, desired: Any, parent: Action | None) -> str: ...

    def display(self, desired: Any, parent: Action | None) -> str:
        return self.key(desired, parent)

    # ---- observed state
    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        return []

    def match(self, desired: Any, observed: list[Observed]) -> list[Observed]:
        name = desired.get("name") if isinstance(desired, dict) else None
        return [o for o in observed if o.body.get("name") == name]

    # ---- planning
    @abstractmethod
    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action: ...

    def ready_for_children(self, action: Action) -> bool:
        """Can children of this resource be observed now? (It exists in Capella.)"""
        return action.observed is not None

    def manages(self, observed: Observed) -> bool:
        """False for system objects (for example the _default and _system scopes): never pruned or listed as unmanaged."""
        return True

    def unmanaged_label(self, observed: Observed, parent: Action | None) -> str:
        """How an undeclared resource is listed under 'Unmanaged' (only when `reports_unmanaged`)."""
        name = observed.body.get("name", observed.id)
        return f"{self.kind} {parent.key}/{name}" if parent else f"{self.kind} {name}"

    def delete_action(self, ctx: RunContext, observed: Observed, parent: Action | None) -> Action:
        """The DELETE (or BLOCKED) action for an undeclared resource; only called when `prunable`."""
        raise NotImplementedError(f"{self.kind} cannot be pruned by this build")

    # ---- applying
    def apply(self, ctx: RunContext, action: Action) -> None:
        raise NotImplementedError(f"{self.kind} cannot be applied by this build")

    def wait(self, ctx: RunContext, action: Action) -> None:
        return None

    def refresh(self, ctx: RunContext, action: Action) -> Action:
        """Re-observe one resource and re-diff it (used after 409/412/ambiguous writes)."""
        found = self.match(action.desired, self.observe(ctx, action.parent))
        return self.diff(ctx, action.desired, found[0] if found else None, action.parent)

    def ensure_ready(self, ctx: RunContext, action: Action, child: Action | None = None) -> bool:
        """Called before `child` is applied. Waits if needed; returns False if the child must be deferred."""
        return True

    def child_block_reason(self, ctx: RunContext, action: Action, child_kind: str) -> str | None:
        """Why a change to a `child_kind` resource below this one cannot be made now (planned as BLOCKED)."""
        return None

    def after_children_note(self) -> str:
        return f"(after {self.kind} is created)"
