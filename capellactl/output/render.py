"""Text and JSON renderers for plans and apply results (00-architecture.md sections 5.2 and 11)."""

from __future__ import annotations

import json
from typing import Any

from capellactl.engine.clock import format_duration
from capellactl.output.redact import redact, redact_obj
from capellactl.resources.base import SYMBOL, Action, ActionType, Plan


def fmt_value(v: Any) -> str:
    if v is None:
        return "(none)"
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, list):
        return "[" + ", ".join(fmt_value(x).strip('"') for x in v) + "]"
    if isinstance(v, dict):
        return json.dumps(v, sort_keys=True)
    return str(v)


def action_line(a: Action) -> list[str]:
    sym = SYMBOL[a.type]
    head = f"  {sym} {a.kind} {a.key}"
    if a.type is ActionType.CREATE and a.summary:
        head += f"  {a.summary}"
    if a.type is ActionType.UPDATE and a.label:
        head += f"   {a.label}"
    if a.type is ActionType.BLOCKED and a.reason:
        head += f"  {a.reason}"
    if a.type is ActionType.DEFERRED:
        head += f"  {a.summary or ''} — {a.reason or 'deferred'}"
    if a.notes:
        head += "  " + " ".join(a.notes)
    lines = [head]
    for c in a.changes:
        if c.before is None and isinstance(c.after, str) and c.path.startswith("serviceGroups["):
            lines.append(f"    + {c.path}  {c.after}")
        elif c.after is None and isinstance(c.before, str) and c.path.startswith("serviceGroups["):
            lines.append(f"    - {c.path}  {c.before}")
        else:
            lines.append(f"      {c.path}:  {fmt_value(c.before)} → {fmt_value(c.after)}")
    lines += [f"      {r}" for r in a.remarks]
    if a.type is ActionType.BLOCKED and a.topic:
        lines.append(f"      See: capellactl help {a.topic}")
    return lines


def render_plan_text(plan: Plan, header: str | None = None) -> str:
    out: list[str] = []
    if header:
        out += [header, ""]
    for a in plan.visible():
        out += action_line(a)
    if plan.unmanaged:
        out += ["", "Unmanaged (not in capella.yaml; use --prune to delete):"]
        out += [f"    {label}" for label in plan.unmanaged]
    out += ["", plan.summary_line()]
    return redact("\n".join(out))


def render_plan_json(plan: Plan) -> dict[str, Any]:
    return dict(redact_obj({"plan": plan.to_json()}))


def dumps(obj: Any) -> str:
    return redact(json.dumps(redact_obj(obj), indent=2, sort_keys=False, default=str))


def render_summary_table(actions: list[Action]) -> str:
    rows = [("KIND", "NAME", "ACTION", "STATUS", "DURATION")]
    for a in actions:
        if a.hidden or a.type is ActionType.NOOP:
            continue
        dur = format_duration(a.duration) if a.duration else "-"
        rows.append((a.kind, a.key, a.type.value, a.status, dur))
    if len(rows) == 1:
        return ""
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    return redact("\n".join("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in rows))
