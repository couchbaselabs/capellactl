"""Execute a plan in dependency order (CAP-006).

- Stops at the first failure; later actions are reported as skipped. Re-running apply resumes,
  because completed actions are then observed as unchanged.
- 409 on create: re-observe and adopt the existing resource.
- 412 on update: re-observe, re-plan that resource and retry once.
- Ambiguous POST (no response): re-observe before deciding; never create twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from capellactl.api.errors import AmbiguousWriteError, CapellaApiError, Conflict, PreconditionFailed
from capellactl.engine.clock import format_duration
from capellactl.engine.context import RunContext
from capellactl.engine.waiter import WaitFailed, WaitTimeout
from capellactl.resources.base import WRITE_TYPES, Action, ActionType, Plan


class ConcurrentChange(Exception):
    pass


@dataclass
class ApplyResult:
    actions: list[Action]
    failed: Action | None = None
    error: BaseException | None = None
    interrupted: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.failed is None and not self.interrupted

    def to_json(self) -> dict[str, Any]:
        status = "interrupted" if self.interrupted else ("failed" if self.failed else "ok")
        out: dict[str, Any] = {
            "status": status,
            "actions": [
                {"kind": a.kind, "key": a.key, "action": a.type.value, "status": a.status, "id": a.id,
                 "durationSeconds": round(a.duration, 3), **({"error": a.error} if a.error else {})}
                for a in self.actions if not a.hidden or a.type in WRITE_TYPES
            ],
        }
        out.update(self.extra)
        return out


def _parent_blocked(action: Action) -> str | None:
    p = action.parent
    while p is not None:
        if p.status in ("failed", "skipped", "deferred"):
            return p.status
        p = p.parent
    return None


def _apply_one(ctx: RunContext, action: Action) -> None:
    rec = action.reconciler
    try:
        rec.apply(ctx, action)
    except Conflict:
        if action.type is not ActionType.CREATE:
            raise
        fresh = rec.refresh(ctx, action)
        if fresh.observed is None:
            raise
        action.observed = fresh.observed
        ctx.progress(f"  {action.kind} {action.key} already exists; using it")
        if fresh.type is ActionType.UPDATE:
            action.type = ActionType.UPDATE
            action.changes = fresh.changes
            rec.apply(ctx, action)
    except AmbiguousWriteError:
        fresh = rec.refresh(ctx, action)
        if fresh.observed is None:
            raise
        action.observed = fresh.observed
        ctx.progress(f"  {action.kind} {action.key} was created despite the lost response; using it")
    except PreconditionFailed:
        fresh = rec.refresh(ctx, action)
        if fresh.type is ActionType.NOOP:
            action.observed = fresh.observed
            return
        action.observed, action.changes = fresh.observed, fresh.changes
        try:
            rec.apply(ctx, action)
        except PreconditionFailed:
            raise ConcurrentChange(f"{action.kind} {action.key} changed concurrently; re-run plan") from None


def execute(ctx: RunContext, plan: Plan) -> ApplyResult:
    result = ApplyResult(plan.actions)
    stop = False
    for action in plan.actions:
        if stop:
            if action.type in WRITE_TYPES and not action.hidden:
                action.status = "skipped"
            continue
        why = _parent_blocked(action)
        if why in ("failed", "skipped"):
            action.status = "skipped"
            continue
        if action.type is ActionType.DEFERRED:
            action.status = "deferred"
            continue
        if action.type is ActionType.NOOP or (action.hidden and action.type is not ActionType.CREATE):
            action.status = "unchanged"
            continue
        if action.type is ActionType.BLOCKED:
            action.status = "blocked"
            continue
        if why == "deferred":
            action.status = "deferred"
            action.notes.append(f"(waiting for {action.parent.kind if action.parent else 'parent'})")
            continue
        parent = action.parent
        if parent is not None and not parent.reconciler.ensure_ready(ctx, parent, action):
            action.status = "deferred"
            action.notes.append(f"(deferred: {parent.kind} {parent.key} is {parent.data.get('state', 'not ready')})")
            continue

        verb = {ActionType.CREATE: "creating", ActionType.UPDATE: "updating", ActionType.REPLACE: "replacing",
                ActionType.DELETE: "deleting"}[action.type]
        ctx.progress(f"→ {verb} {action.kind} {action.key} …")
        started = ctx.clock.monotonic()
        try:
            _apply_one(ctx, action)
            if not ctx.no_wait:
                try:
                    action.reconciler.wait(ctx, action)
                except KeyboardInterrupt:
                    action.error = "stopped waiting; the operation continues in Capella"
                    raise
            action.status = "done"
            action.duration = ctx.clock.monotonic() - started
            ctx.progress(f"  done {action.kind} {action.key} in {format_duration(action.duration)}")
        except KeyboardInterrupt:
            action.status = "interrupted"
            result.interrupted = True
            result.failed = action
            stop = True
        except (CapellaApiError, AmbiguousWriteError, ConcurrentChange, WaitFailed, WaitTimeout, Exception) as exc:
            action.status = "failed"
            action.error = str(exc)
            action.duration = ctx.clock.monotonic() - started
            result.failed = action
            result.error = exc
            stop = True
    return result
