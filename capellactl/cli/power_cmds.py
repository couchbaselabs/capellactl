"""cluster power NAME --on|--off: on-demand hibernation (CAP-019).

Turning a cluster off keeps its storage, data, schema and configuration; nothing in capella.yaml changes, because
power is not part of the file (the on/off schedule is, CAP-020).
"""

from __future__ import annotations

from typing import Any

import click

from capellactl.api import endpoints as ep
from capellactl.api.errors import Conflict, NotFound
from capellactl.cli import console
from capellactl.cli.console import out, wait_progress
from capellactl.cli.env import pass_state
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.resource_cmds import complete_cluster_names, live_cluster
from capellactl.cli.state import AppState
from capellactl.engine.clock import get_clock
from capellactl.engine.waiter import WaitFailed, WaitTimeout, wait_for_cluster

OFF_NOTES = ("Turning it off stops the compute; storage remains. All data, schema (buckets, scopes, collections) "
             "and indexes remain, as well as the cluster configuration, including users and allow lists.\n"
             "Linked App Services are turned off too. Charges for the Data API continue.")


def _state(client: Any, pid: str, cid: str, free: bool) -> str:
    body, _ = (ep.get_free_cluster if free else ep.get_cluster)(client, pid, cid)
    return str(body.get("currentState", "unknown"))


def _wait(state: AppState, client: Any, pid: str, cid: str, name: str, op: Any, free: bool = False) -> None:
    on_state, on_tick = wait_progress(f"cluster {name}")
    try:
        wait_for_cluster(client, pid, cid, op, state.timeout, get_clock(), on_state, name=name, on_tick=on_tick,
                         getter=ep.get_free_cluster if free else None)
    except WaitFailed as exc:
        raise CliExit(ExitCode.ERROR, f"Failed: {exc.what}",
                                      action=exc.action) from None
    except WaitTimeout as exc:
        raise CliExit(ExitCode.TIMEOUT, exc.what,
                                        action=exc.action) from None


def schedule_note(client: Any, pid: str, cid: str) -> str | None:
    """`note: the on/off schedule will turn this cluster on at Mon 08:00 US/Pacific` (CAP-019 AC7)."""
    from capellactl.resources.schedule import next_on_text

    try:
        body, _ = ep.get_schedule(client, pid, cid)
    except NotFound:
        return None
    if body.get("activationStatus") == "paused":
        return None
    when = next_on_text(body, get_clock().now())
    return f"note: the on/off schedule will turn this cluster on at {when}" if when else None


def power(state: AppState, client: Any, pid: str, cl: dict[str, Any], on: bool, with_app_service: bool = False,
          confirm: bool = True) -> None:
    """Bring a cluster to on (healthy) or off (turnedOff); waits unless --no-wait. Shared with schedule pause."""
    from capellactl.resources.cluster import is_free

    name, cid, free = str(cl.get("name")), str(cl["id"]), is_free(cl)
    target = "healthy" if on else "turnedOff"
    current = str(cl.get("currentState", "unknown"))
    for attempt in (1, 2):
        if current == target:
            out(f"cluster {name} is already {'on' if on else 'off'}; nothing to do")
            return
        if current in ("turningOn", "turningOff"):  # in transition: let it finish first (AC4)
            going = "healthy" if current == "turningOn" else "turnedOff"
            if state.no_wait:
                raise CliExit(ExitCode.BLOCKED, f"cluster {name} is {current}",
                                                action=f"Wait until it is healthy or turned off ('capellactl cluster "
                                                       f"get {name}' shows its state), then run the command again.")
            _wait(state, client, pid, cid, name, "power_on" if current == "turningOn" else "power_off", free)
            if going == target:
                out(f"cluster {name} is {'on' if on else 'off'}")
                return
            current = going
        if current not in ("healthy", "turnedOff"):
            raise CliExit(ExitCode.BLOCKED, f"cluster {name} is {current}; it can be turned "
                                            f"{'on' if on else 'off'} only when it is "
                                            f"{'turned off' if on else 'healthy'}", topic="hibernation",
                                            action=f"Wait until it is {'turned off' if on else 'healthy'} "
                                                   f"('capellactl cluster get {name}' shows its state), then run the "
                                                   f"command again.")
        if not on and confirm and attempt == 1 \
                and not console.confirm(state, f"Turn off cluster {name}?", "turn off a cluster", notes=OFF_NOTES):
            out("Cancelled; the cluster is unchanged.")
            return
        try:
            if free:  # free tier: its own endpoints; turning on always includes linked App Services
                (ep.turn_free_cluster_on if on else ep.turn_free_cluster_off)(client, pid, cid)
            elif on:
                ep.turn_cluster_on(client, pid, cid, with_app_service)
            else:
                ep.turn_cluster_off(client, pid, cid)
        except Conflict as exc:  # someone else changed it: re-read once (AC5)
            if attempt == 2:
                raise CliExit(ExitCode.ERROR, f"Capella refused: {exc}",
                                              action="Someone else is changing the cluster: wait until that "
                                                     "finishes, then run the command again.") from None
            current = _state(client, pid, cid, free)
            continue
        break
    if state.no_wait:
        out(f"cluster {name} is turning {'on' if on else 'off'} (--no-wait)")
        return
    _wait(state, client, pid, cid, name, "power_on" if on else "power_off", free)
    if on:
        out(f"cluster {name} is on")
    else:
        out(f"cluster {name} is off (storage, data and configuration retained)")
        note = schedule_note(client, pid, cid)
        if note:
            out(note)


@click.command("power", epilog="\b\nExamples:\n  capellactl cluster power nova-dev-01 --off\n"
                               "  capellactl cluster power nova-dev-01 --on\n"
                               "  capellactl cluster power nova-dev-01 --on --with-app-service")
@click.argument("name", shell_complete=complete_cluster_names)
@click.option("--on/--off", "on", default=None, help="Turn the cluster on or off.")
@click.option("--with-app-service", is_flag=True, help="With --on: also turn on the linked App Service.")
@click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name repeats).")
@pass_state
def cluster_power(state: AppState, name: str, on: bool | None, with_app_service: bool, project: str | None) -> None:
    """Turn a cluster off (storage and data kept, compute stopped) or on again."""
    if on is None:
        raise CliExit(ExitCode.CONFIG_INVALID, "nothing to do: neither --on nor --off was given", topic="hibernation",
                                               action="Add --on to turn the cluster on, or --off to turn it off.")
    client, pid, cl = live_cluster(state, name, project)
    power(state, client, pid, cl, on, with_app_service)
