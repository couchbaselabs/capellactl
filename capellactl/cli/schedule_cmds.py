"""cluster schedule show | set | apply | pause | resume | delete: the hibernation schedule (CAP-020, CAP-021).

`set`, `pause`, `resume` and `delete` record the result in capella.yaml (`hibernation:`), like every other command,
so the next apply keeps it and sync finds nothing to change.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

import click
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from capellactl.api import endpoints as ep
from capellactl.api.errors import NotFound
from capellactl.cli import console
from capellactl.cli.cluster_ops import change_and_apply, locate, open_editor
from capellactl.cli.console import err, out
from capellactl.cli.env import pass_state
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.groups import SuggestingGroup
from capellactl.cli.resource_cmds import complete_cluster_names, live_cluster, project_of_cluster
from capellactl.cli.state import AppState
from capellactl.config.editor import ConfigEditor, put, to_commented
from capellactl.engine.clock import get_clock
from capellactl.output.render import dumps
from capellactl.resources.schedule import DAYS, grid, next_text, next_transition, week_summary

_F = TypeVar("_F", bound=Callable[..., Any])
PROJECT_OPT = click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name "
                                                             "repeats).")
NAME_ARG = click.argument("name", shell_complete=complete_cluster_names)


@click.group("schedule", cls=SuggestingGroup, epilog="\b\nExamples:\n"
             "  capellactl cluster schedule set nova-dev-01 --timezone US/Pacific --weekdays 08:00-18:00 --weekend off\n"
             "  capellactl cluster schedule show nova-dev-01\n"
             "  capellactl cluster schedule pause nova-dev-01 --power-on     (demo or incident: keep it on)\n"
             "  capellactl cluster schedule resume nova-dev-01\n"
             "  capellactl cluster schedule delete nova-dev-01")
def schedule() -> None:
    """Hibernation schedule: Capella turns the cluster off outside the on-windows (show, set, pause, resume, delete)."""


def _get(client: Any, pid: str, cid: str, name: str) -> dict[str, Any]:
    try:
        return ep.get_schedule(client, pid, cid)[0]
    except NotFound:
        raise CliExit(ExitCode.BLOCKED, f"cluster {name} has no on/off schedule; create one with 'capellactl "
                                        f"cluster schedule set {name} --timezone TZ --weekdays HH:MM-HH:MM'",
                      topic="hibernation") from None


# --------------------------------------------------------------------- show
@schedule.command("show", epilog="\b\nExamples:\n  capellactl cluster schedule show nova-dev-01\n"
                                 "  capellactl -o json cluster schedule show nova-dev-01")
@NAME_ARG
@PROJECT_OPT
@pass_state
def schedule_show(state: AppState, name: str, project: str | None) -> None:
    """Show the weekly on/off grid and the next transition (CAP-020 AC7)."""
    client, pid, cl = live_cluster(state, name, project)
    body = _get(client, pid, str(cl["id"]), name)
    found = next_transition(body, get_clock().now()) if body.get("activationStatus") != "paused" else None
    if state.json:
        payload: dict[str, Any] = {"cluster": name, **body}
        if found:
            payload["nextTransition"] = {"state": found[0], "at": found[1].isoformat()}
        out(dumps(payload))
        return
    out(f"{name}  {body.get('timezone')}  {body.get('activationStatus', 'active')}")
    for line in grid(body):
        out(line)
    if found:
        out(f"Next: {next_text(body, get_clock().now())}")
    elif body.get("activationStatus") == "paused":
        out("Paused: the cluster stays in its current state until 'capellactl cluster schedule resume " + name + "'")


# ---------------------------------------------------------------------- set
def _day_option(name: str) -> Callable[[_F], _F]:
    return click.option(f"--{name}", metavar="WINDOW", help=f"{name.capitalize()}: on, off or HH:MM-HH:MM "
                                                              "(overrides --weekdays/--weekend).")


@schedule.command("set", epilog="\b\nExamples:\n"
                  "  capellactl cluster schedule set nova-dev-01 --timezone US/Pacific --weekdays 08:00-18:00 "
                  "--weekend off\n"
                  "  capellactl cluster schedule set nova-dev-01 --friday 08:00-14:30\n"
                  "  capellactl cluster schedule set nova-dev-01 --wednesday on")
@NAME_ARG
@click.option("--timezone", metavar="TZ", help="Schedule timezone, for example US/Pacific, Europe/London, "
                                                "Asia/Calcutta (needed for a new schedule).")
@click.option("--weekdays", metavar="WINDOW", help="Monday–Friday: on, off or an on-window HH:MM-HH:MM "
                                                   "(minutes 00 or 30).")
@click.option("--weekend", metavar="WINDOW", help="Saturday and Sunday: on, off or HH:MM-HH:MM.")
@_day_option("monday")
@_day_option("tuesday")
@_day_option("wednesday")
@_day_option("thursday")
@_day_option("friday")
@_day_option("saturday")
@_day_option("sunday")
@PROJECT_OPT
@click.option("--no-apply", is_flag=True, help="Only record the schedule in capella.yaml; apply later.")
@pass_state
def schedule_set(state: AppState, name: str, timezone: str | None, weekdays: str | None, weekend: str | None,
                 monday: str | None, tuesday: str | None, wednesday: str | None, thursday: str | None,
                 friday: str | None, saturday: str | None, sunday: str | None, project: str | None,
                 no_apply: bool) -> None:
    """Create or change the schedule: records it in capella.yaml and applies it (CAP-020)."""
    days = dict(zip(DAYS, (monday, tuesday, wednesday, thursday, friday, saturday, sunday), strict=True))
    ed = open_editor(state)
    _, cl = locate(ed, name, project_of_cluster(state, name, project))
    hib = cl.get("hibernation")
    new = not isinstance(hib, CommentedMap) or hib.get("ensure") == "absent"
    values = {"timezone": timezone, "weekdays": weekdays, "weekend": weekend, **days}
    if not any(v is not None for v in values.values()):
        raise CliExit(ExitCode.CONFIG_INVALID, "pass at least one of --timezone, --weekdays, --weekend or a day "
                                               "option (for example --friday 08:00-14:30)", topic="hibernation")
    if new:
        if not timezone:
            raise CliExit(ExitCode.CONFIG_INVALID, "a new schedule needs --timezone (for example US/Pacific)",
                          topic="hibernation")
        hib = to_commented({}, "hibernation")
        put(cl, "hibernation", hib)
    assert isinstance(hib, CommentedMap)
    hib.pop("ensure", None)
    for key in ("timezone", "weekdays", "weekend", *DAYS):
        v = values.get(key)
        if v is not None:  # quoted: an unquoted on/off would load as a YAML boolean
            hib[key] = v if key == "timezone" else DoubleQuotedScalarString(v)
    if weekdays is not None:  # a new weekdays value replaces earlier per-day overrides for Monday–Friday
        for d in DAYS[:5]:
            if values.get(d) is None:
                hib.pop(d, None)
    if weekend is not None:
        for d in DAYS[5:]:
            if values.get(d) is None:
                hib.pop(d, None)
    change_and_apply(state, ed, f"schedule/{name}",
                     f"Record this schedule in capella.yaml and apply it to {name}?", no_apply,
                     noop_message=f"schedule of {name} already matches; capella.yaml is up to date")


# -------------------------------------------------------------------- apply
@schedule.command("apply", epilog="\b\nExamples:\n  capellactl cluster schedule apply nova-dev-01")
@NAME_ARG
@pass_state
def schedule_apply(state: AppState, name: str) -> None:
    """Apply only the schedule that capella.yaml records for this cluster."""
    from capellactl.cli.env import run_apply

    run_apply(state, [f"schedule/{name}"])


# ----------------------------------------------------------- pause / resume
def _record_paused(state: AppState, name: str, project: str | None, paused: bool) -> None:
    """Keep capella.yaml in step: `paused: true` while paused; removed on resume (as import writes it)."""
    path = state.config_path()
    if not path.exists():
        return
    ed = ConfigEditor(path)
    try:
        found = ed.find_cluster(name, project)
    except LookupError:
        return
    hib = found[1].get("hibernation") if found else None
    if not isinstance(hib, CommentedMap):
        return
    if paused == bool(hib.get("paused")):
        return
    if paused:
        hib["paused"] = True
    else:
        hib.pop("paused", None)
    backup = ed.save()
    err(f"{path.name} updated: {'paused: true' if paused else 'paused removed'} for {name} "
        f"(previous version kept as {backup.name})")


@schedule.command("pause", epilog="\b\nExamples:\n  capellactl cluster schedule pause nova-dev-01\n"
                                  "  capellactl cluster schedule pause nova-dev-01 --power-on")
@NAME_ARG
@click.option("--power-on", is_flag=True, help="Also turn the cluster on if the schedule has turned it off.")
@PROJECT_OPT
@pass_state
def schedule_pause(state: AppState, name: str, power_on: bool, project: str | None) -> None:
    """Pause the schedule: the cluster stays as it is until resumed (CAP-021)."""
    from capellactl.cli.power_cmds import power

    client, pid, cl = live_cluster(state, name, project)
    body = _get(client, pid, str(cl["id"]), name)
    owner = project_of_cluster(state, name, project)
    if body.get("activationStatus") == "paused":
        out(f"schedule of {name} is already paused; nothing to do in Capella")
    else:
        ep.pause_schedule(client, pid, str(cl["id"]))
        now = "off" if cl.get("currentState") in ("turnedOff", "turningOff") else "on"
        out(f"schedule paused; cluster will stay in its current state ({now}) until resumed")
    _record_paused(state, name, owner, True)
    if power_on and cl.get("currentState") in ("turnedOff", "turningOff"):
        power(state, client, pid, cl, True)


@schedule.command("resume", epilog="\b\nExamples:\n  capellactl cluster schedule resume nova-dev-01")
@NAME_ARG
@PROJECT_OPT
@pass_state
def schedule_resume(state: AppState, name: str, project: str | None) -> None:
    """Resume a paused schedule and show its next transition (CAP-021)."""
    client, pid, cl = live_cluster(state, name, project)
    body = _get(client, pid, str(cl["id"]), name)
    owner = project_of_cluster(state, name, project)
    if body.get("activationStatus") != "paused":
        out(f"schedule of {name} is already active; nothing to do in Capella")
    else:
        ep.resume_schedule(client, pid, str(cl["id"]))
        body["activationStatus"] = "active"
        nxt = next_text(body, get_clock().now())
        out(f"schedule resumed{f'; next: {nxt}' if nxt else ''}")
    _record_paused(state, name, owner, False)


# ------------------------------------------------------------------- delete
@schedule.command("delete", epilog="\b\nExamples:\n  capellactl cluster schedule delete nova-dev-01")
@NAME_ARG
@PROJECT_OPT
@pass_state
def schedule_delete(state: AppState, name: str, project: str | None) -> None:
    """Delete the schedule in Capella and remove it from capella.yaml (the cluster stays as it is)."""
    owner = project_of_cluster(state, name, project)
    client, pid, cl = live_cluster(state, name, project)
    try:
        body: dict[str, Any] | None = ep.get_schedule(client, pid, str(cl["id"]))[0]
    except NotFound:
        body = None
    if body is not None:
        out(f"  - schedule {name}  {week_summary(body)}")
        if not state.auto_approve:
            if not console.is_interactive():
                raise CliExit(ExitCode.ERROR, "refusing to delete the schedule without --auto-approve in a "
                                              "non-interactive session")
            if not click.confirm(f"Delete the on/off schedule of {name}? The cluster stays in its current state.",
                                 default=False):
                out("Cancelled; the schedule is unchanged.")
                return
        ep.delete_schedule(client, pid, str(cl["id"]))
        out(f"deleted the on/off schedule of {name}")
    else:
        out(f"cluster {name} has no on/off schedule; nothing to do in Capella")
    path = state.config_path()
    if path.exists():
        ed = ConfigEditor(path)
        try:
            found = ed.find_cluster(name, owner)
        except LookupError:
            found = None
        if found is not None and "hibernation" in found[1]:
            del found[1]["hibernation"]
            backup = ed.save()
            err(f"{path.name} updated: hibernation removed for {name} (previous version kept as {backup.name})")
