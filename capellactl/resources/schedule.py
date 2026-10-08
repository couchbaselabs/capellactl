"""Hibernation (on/off) schedule reconciler (CAP-020) with the declarative paused flag (CAP-021).

The file uses a friendly form (`weekdays: "08:00-18:00"`, `weekend: "off"`, per-day overrides); Capella takes 7 days
Monday → Sunday, each `on`, `off` or `custom` with `from`/`to`. Both are compared in the expanded API form, so
either form in the file gives the same plan.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
from typing import Any

from capellactl.api import endpoints as ep
from capellactl.api.errors import NotFound
from capellactl.engine.context import RunContext
from capellactl.resources.base import Action, ActionType, Change, Observed, Reconciler

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SHORT = {d: d[:3].capitalize() for d in DAYS}
WEEKDAYS, WEEKEND = DAYS[:5], DAYS[5:]


# ------------------------------------------------------------------ friendly ⇄ API form
def _hm(text: str) -> dict[str, int]:
    h, m = text.split(":")
    return {"hour": int(h) % 24, "minute": int(m)}  # 24:00 (end of day) is sent as 0:00


def day_value(hib: dict[str, Any], day: str) -> str:
    """The friendly value for one day: the per-day key, else weekdays/weekend, else 'on'."""
    group = "weekdays" if day in WEEKDAYS else "weekend"
    value = hib.get(day, hib.get(group, "on"))
    if isinstance(value, bool):  # unquoted on/off (CAP-020 AC10)
        return "on" if value else "off"
    return str(value)


def expand_day(day: str, value: str) -> dict[str, Any]:
    if value in ("on", "off"):
        return {"day": day, "state": value}
    start, end = value.split("-", 1)
    return {"day": day, "state": "custom", "from": _hm(start), "to": _hm(end)}


def expand(hib: dict[str, Any]) -> dict[str, Any]:
    """Friendly form → API body: timezone and 7 days, Monday → Sunday (CAP-020 AC1)."""
    return {"timezone": hib.get("timezone"), "days": [expand_day(d, day_value(hib, d)) for d in DAYS]}


def _fmt(b: dict[str, Any] | None, end: bool = False) -> str:
    h, m = int((b or {}).get("hour", 0)), int((b or {}).get("minute", 0))
    return "24:00" if end and h == 0 and m == 0 else f"{h:02d}:{m:02d}"


def day_text(entry: dict[str, Any]) -> str:
    """One API day as text: on, off or 08:00–18:00."""
    if entry.get("state") in ("on", "off"):
        return str(entry["state"])
    return f"{_fmt(entry.get('from'))}–{_fmt(entry.get('to'), end=True)}"


def by_day(body: dict[str, Any]) -> dict[str, str]:
    return {str(e.get("day")): day_text(e) for e in body.get("days") or []}


def week_summary(body: dict[str, Any]) -> str:
    """`US/Pacific · Mon–Thu 08:00–18:00 · Fri 08:00–14:30 · Sat–Sun off` (runs of equal days)."""
    days = by_day(body)
    parts: list[str] = [str(body.get("timezone"))]
    i = 0
    while i < len(DAYS):
        j = i
        while j + 1 < len(DAYS) and days.get(DAYS[j + 1]) == days.get(DAYS[i]):
            j += 1
        span = SHORT[DAYS[i]] if i == j else f"{SHORT[DAYS[i]]}–{SHORT[DAYS[j]]}"
        parts.append(f"{span} {days.get(DAYS[i], '?')}")
        i = j + 1
    return " · ".join(parts)


# ------------------------------------------------------------------ time
def _zone(tz: str) -> Any:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz)
    except Exception:  # noqa: BLE001 - no tz database on this machine: no next-transition line
        return None


def state_at(body: dict[str, Any], local: datetime) -> str:
    """'on' or 'off' at a local time."""
    entry = next((e for e in body.get("days") or [] if e.get("day") == DAYS[local.weekday()]), None)
    if entry is None or entry.get("state") == "on":
        return "on"
    if entry.get("state") == "off":
        return "off"
    start = int(entry["from"]["hour"]) * 60 + int(entry["from"]["minute"])
    to = entry.get("to") or {"hour": 0, "minute": 0}
    end = int(to["hour"]) * 60 + int(to["minute"]) or 24 * 60
    minute = local.hour * 60 + local.minute
    return "on" if start <= minute < end else "off"


def next_transition(body: dict[str, Any], now: datetime) -> tuple[str, datetime] | None:
    """The next time the schedule turns the cluster on or off: (state, local time), or None (CAP-020 AC7).

    Boundaries are on the hour or half hour, so 30-minute steps over 8 days find it."""
    tz = _zone(str(body.get("timezone")))
    if tz is None:
        return None
    local = now.astimezone(tz)
    current = state_at(body, local)
    t = local.replace(second=0, microsecond=0)
    t += timedelta(minutes=30 - t.minute % 30)
    for _ in range(8 * 48):
        s = state_at(body, t)
        if s != current:
            return s, t
        t += timedelta(minutes=30)
    return None


def next_text(body: dict[str, Any], now: datetime) -> str | None:
    found = next_transition(body, now)
    if found is None:
        return None
    s, at = found
    return f"{s} at {at.strftime('%a %H:%M')} {body.get('timezone')}"


def next_on_text(body: dict[str, Any], now: datetime) -> str | None:
    """`Mon 08:00 US/Pacific`: when the schedule next turns the cluster on (CAP-019 AC7)."""
    tz = _zone(str(body.get("timezone")))
    if tz is None:
        return None
    t = now.astimezone(tz).replace(second=0, microsecond=0)
    t += timedelta(minutes=30 - t.minute % 30)
    was = state_at(body, now.astimezone(tz))
    for _ in range(8 * 48):
        s = state_at(body, t)
        if s == "on" and was == "off":
            return f"{t.strftime('%a %H:%M')} {body.get('timezone')}"
        was = s
        t += timedelta(minutes=30)
    return None


def grid(body: dict[str, Any]) -> list[str]:
    """One line per day: 24 hourly cells (█ on, ░ off) and the day's value."""
    lines = []
    days = by_day(body)
    for i, d in enumerate(DAYS):
        base = datetime(2026, 1, 5 + i)  # 2026-01-05 is a Monday
        cells = "".join("█" if state_at(body, base + timedelta(hours=h, minutes=0)) == "on" else "░"
                        for h in range(24))
        lines.append(f"{SHORT[d]} {cells}  {days.get(d, '?')}")
    return lines


# ------------------------------------------------------------------ reconciler
def _ids(cluster: Action | None) -> tuple[str, str]:
    project = cluster.ancestor("project") if cluster is not None else None
    assert cluster is not None and cluster.id is not None and project is not None and project.id is not None
    return project.id, cluster.id


class ScheduleReconciler(Reconciler):
    kind = "schedule"
    story = "CAP-020"
    prunable = True  # `apply --prune` deletes a schedule the file does not declare (CAP-031)
    reports_unmanaged = True  # without a hibernation key an existing schedule is left alone, and listed

    def desired_items(self, parent_desired: Any) -> list[Any]:
        if isinstance(parent_desired, dict) and isinstance(parent_desired.get("hibernation"), dict):
            return [parent_desired["hibernation"]]
        return []

    def key(self, desired: Any, parent: Action | None) -> str:
        return parent.key if parent else ""

    def unmanaged_label(self, observed: Observed, parent: Action | None) -> str:
        return f"schedule {parent.key if parent else ''}  {week_summary(observed.body)}"

    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        pid, cid = _ids(parent)
        try:
            body, etag = ep.get_schedule(ctx.client, pid, cid)
        except NotFound:
            return []
        return [Observed(cid, body, etag)]

    def match(self, desired: Any, observed: list[Observed]) -> list[Observed]:
        return observed[:1]

    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        key = self.key(desired, parent)
        if desired.get("ensure") == "absent":
            if observed is None:
                return Action(self.kind, key, ActionType.NOOP, self, desired=desired, parent=parent, hidden=True)
            return Action(self.kind, key, ActionType.DELETE, self, desired=desired, observed=observed, parent=parent,
                          summary=week_summary(observed.body))
        want = expand(desired)
        if observed is None:
            a = Action(self.kind, key, ActionType.CREATE, self, desired=desired, parent=parent,
                       summary=week_summary(want) + (" · paused" if desired.get("paused") else ""))
            a.data["body"] = want
            return a
        have = observed.body
        changes: list[Change] = []
        if have.get("timezone") != want["timezone"]:
            changes.append(Change("timezone", have.get("timezone"), want["timezone"]))
        old, new = by_day(have), by_day(want)
        changes += [Change(d, old.get(d), new[d]) for d in DAYS if old.get(d) != new[d]]
        a = Action(self.kind, key, ActionType.NOOP, self, desired=desired, observed=observed, parent=parent)
        a.data["body"] = want
        a.data["put"] = bool(changes)
        status = have.get("activationStatus", "active")
        if "paused" in desired and (status == "paused") != bool(desired["paused"]):
            target = "paused" if desired["paused"] else "active"
            changes.append(Change("activationStatus", status, target))
            a.data["status"] = target
        if changes:
            a.type, a.changes = ActionType.UPDATE, changes
        return a

    def delete_action(self, ctx: RunContext, observed: Observed, parent: Action | None) -> Action:
        return Action(self.kind, self.key({}, parent), ActionType.DELETE, self, desired={"ensure": "absent"},
                      observed=observed, parent=parent, summary=week_summary(observed.body))

    def apply(self, ctx: RunContext, action: Action) -> None:
        pid, cid = _ids(action.parent)
        if action.type is ActionType.DELETE:
            with contextlib.suppress(NotFound):
                ep.delete_schedule(ctx.client, pid, cid)
            return
        if action.type is ActionType.CREATE:
            ep.create_schedule(ctx.client, pid, cid, action.data["body"])
            if action.desired.get("paused"):  # created active; pause after the POST (CAP-021 AC6)
                ep.pause_schedule(ctx.client, pid, cid)
            return
        if action.data.get("put"):
            etag = action.observed.etag if action.observed is not None else None
            ep.update_schedule(ctx.client, pid, cid, action.data["body"], if_match=etag)
        status = action.data.get("status")
        if status == "paused":
            ep.pause_schedule(ctx.client, pid, cid)
        elif status == "active":
            ep.resume_schedule(ctx.client, pid, cid)

    def refresh(self, ctx: RunContext, action: Action) -> Action:
        found = self.observe(ctx, action.parent)
        return self.diff(ctx, action.desired, found[0] if found else None, action.parent)
