"""cluster protect (CAP-013) and cluster delete (CAP-014).

`cluster protect` is an ad-hoc switch: it changes Capella only, and says so when capella.yaml declares the
opposite (the next apply restores the file's value). `cluster delete` removes the cluster from Capella,
waits until it is gone, and then removes it from capella.yaml.
"""

from __future__ import annotations

from typing import Any

import click

from capellactl.api import endpoints as ep
from capellactl.api.errors import CapellaApiError, NotFound
from capellactl.cli import console
from capellactl.cli.console import note, out, wait_progress
from capellactl.cli.env import pass_state
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.resource_cmds import (
    _file_org,
    _project_id,
    complete_cluster_names,
    file_cluster,
    live_cluster,
    project_of_cluster,
)
from capellactl.cli.state import AppState
from capellactl.engine.clock import get_clock
from capellactl.engine.waiter import WaitFailed, WaitTimeout, wait_for_cluster
from capellactl.resources.cluster import is_free
from capellactl.resources.guards import deletion_protected, protection_message

PROJECT_OPT = click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name repeats).")


# ------------------------------------------------------------------ protect
@click.command("protect", epilog="\b\nExamples:\n  capellactl cluster protect nova-dev-01 --on\n"
                                 "  capellactl cluster protect nova-dev-01 --off     (before deleting it)")
@click.argument("name", shell_complete=complete_cluster_names)
@click.option("--on/--off", "enable", default=None, help="Turn deletion protection on or off (recorded in capella.yaml).")
@PROJECT_OPT
@pass_state
def cluster_protect(state: AppState, name: str, enable: bool | None, project: str | None) -> None:
    """Turn deletion protection on or off in Capella and record it in capella.yaml."""
    if enable is None:
        raise CliExit(ExitCode.CONFIG_INVALID, "pass --on or --off", topic="safety")
    client, pid, cl = live_cluster(state, name, project)
    word = "on" if enable else "off"
    owner = project_of_cluster(state, name, project)
    if deletion_protected(cl) == enable:
        out(f"deletion protection is already {word} for {name}; nothing to do in Capella")
        _record_protection(state, name, owner, enable)
        return
    if not enable and not console.confirm(state, f"Turn off deletion protection for {name}? The cluster and its "
                                                 "buckets can then be deleted.", "turn off deletion protection"):
        out("Cancelled; deletion protection is unchanged.")
        return
    ep.set_deletion_protection(client, pid, str(cl["id"]), enable)
    out(f"deletion protection {word} for {name}")
    _record_protection(state, name, owner, enable)


def _record_protection(state: AppState, name: str, project: str | None, enable: bool) -> None:
    """Keep capella.yaml in step: `deletionProtection: true` when on; the key is removed when off (as import writes
    it), so the next apply does not undo the command and sync finds nothing to change."""
    from capellactl.config.editor import ConfigEditor, put

    path = state.config_path()
    if not path.exists():
        return
    ed = ConfigEditor(path)
    try:
        found = ed.find_cluster(name, project)
    except LookupError:
        return
    if found is None:
        return
    node = found[1]
    if enable:
        if node.get("deletionProtection") is True:
            return
        put(node, "deletionProtection", True)
    else:
        if "deletionProtection" not in node:
            return
        del node["deletionProtection"]
    backup = ed.save()
    change = "deletionProtection: true" if enable else "deletionProtection removed"
    out(f"{path.name} updated: {change} for {name} (previous version kept as {backup.name})")


# ------------------------------------------------------------------- delete
def _find_for_delete(client: Any, pid: str, name: str, pinned: str | None) -> dict[str, Any] | None:
    """The cluster to delete, by pinned id or name; None when absent. Exit 4 when the name is ambiguous."""
    clusters = ep.list_clusters(client, pid)
    if pinned:
        found = [c for c in clusters if c.get("id") == pinned]
        if not found:  # free-tier clusters are not always listed; read it directly
            try:
                body, _ = ep.get_free_cluster(client, pid, pinned)
                found = [body]
            except NotFound:
                found = []
        return found[0] if found else None
    found = [c for c in clusters if c.get("name") == name]
    if len(found) > 1:
        ids = ", ".join(str(c.get("id")) for c in found)
        raise CliExit(ExitCode.BLOCKED, f"{len(found)} clusters are named {name} (ids: {ids}); pin the one to delete "
                                        "with id: in capella.yaml", topic="idempotency")
    return found[0] if found else None


def _delete_details(client: Any, pid: str, cl: dict[str, Any], discard: bool) -> list[str]:
    """Confirmation lines: where it runs, size, buckets and schedule that go with it, snapshot backups."""
    cid = str(cl["id"])
    cp = cl.get("cloudProvider") or {}
    nodes = sum(int(g.get("numOfNodes") or 0) for g in cl.get("serviceGroups") or [])
    try:
        buckets = ep.list_free_buckets(client, pid, cid)[0] if is_free(cl) else ep.list_buckets(client, pid, cid)
    except CapellaApiError:
        buckets = []
    head = (f"  - cluster {cl.get('name')}  {cp.get('type')} {cp.get('region')} · {nodes} node{'s' if nodes != 1 else ''}"
            f" · {len(buckets)} bucket{'s' if len(buckets) != 1 else ''}")
    lines = [head]
    if buckets:
        names = ", ".join(sorted(str(b.get("name")) for b in buckets))
        lines.append(f"    buckets deleted with the cluster: {names}")
    if not is_free(cl):
        try:
            schedule, _ = ep.get_schedule(client, pid, cid)
        except CapellaApiError:  # 404: no schedule
            schedule = None
        if schedule:
            lines.append(f"    hibernation schedule ({schedule.get('timezone', '?')}) is deleted with the cluster")
    if is_free(cl):  # no snapshot backups on the free tier
        return lines
    if discard:
        lines.append(click.style("    WARNING: snapshot backups will be deleted", fg="red", bold=True))
    else:
        lines.append("    snapshot backups are kept (--discard-snapshots deletes them)")
    return lines


def _wait_gone(state: AppState, client: Any, pid: str, cl: dict[str, Any]) -> None:
    name = str(cl.get("name"))

    on_state, on_tick = wait_progress(f"cluster {name}")
    try:
        wait_for_cluster(client, pid, str(cl["id"]), "delete", state.timeout, get_clock(), on_state, name=name,
                         getter=ep.get_free_cluster if is_free(cl) else None, on_tick=on_tick)
    except WaitFailed as exc:
        raise CliExit(ExitCode.ERROR, f"Failed: {exc}", topic="safety") from None
    except WaitTimeout as exc:
        raise CliExit(ExitCode.TIMEOUT, str(exc)) from None


def _remove_from_file(state: AppState, name: str, project: str | None) -> None:
    """Keep capella.yaml in step, so the next apply does not deploy the cluster again."""
    from capellactl.config.editor import ConfigEditor

    path = state.config_path()
    if not path.exists() or file_cluster(state, name, project) is None:
        return
    ed = ConfigEditor(path)
    try:
        found = ed.find_cluster(name, project)
    except LookupError:
        return
    if found is None:
        return
    ed.remove_cluster(name, found[0])
    backup = ed.save()
    note(f"removed cluster {name} from {path.name} (previous version kept as {backup.name})")


@click.command("delete", epilog="\b\nExamples:\n  capellactl cluster delete nova-dev-01\n"
                                "  capellactl cluster delete nova-dev-01 --discard-snapshots\n"
                                "  capellactl --auto-approve cluster delete nova-ci-01")
@click.argument("name", shell_complete=complete_cluster_names)
@click.option("--discard-snapshots", is_flag=True, help="Also delete the cluster's snapshot backups (kept by default).")
@click.option("--cascade", is_flag=True, help="Accepted for symmetry with 'project delete --cascade': Capella always "
              "deletes a cluster's buckets, schedule and allowed CIDRs with it, and they are listed before you confirm.")
@PROJECT_OPT
@pass_state
def cluster_delete(state: AppState, name: str, discard_snapshots: bool, cascade: bool, project: str | None) -> None:
    """Delete a cluster and all its data, wait until it is gone, and remove it from capella.yaml (CAP-014)."""
    client = state.client(_file_org(state))
    owner = project_of_cluster(state, name, project)
    pid, _ = _project_id(state, client, owner)
    pinned = (file_cluster(state, name, owner) or {}).get("id")
    cl = _find_for_delete(client, pid, name, str(pinned) if pinned else None)
    if cl is None:
        out(f"cluster {name} not found, nothing to do")
        _remove_from_file(state, name, owner)
        return
    if cl.get("currentState") == "destroying":  # deleted earlier (or by someone else): only wait
        out(f"cluster {name} is already being deleted; waiting until it is gone")
        if not state.no_wait:
            _wait_gone(state, client, pid, cl)
            out(f"deleted cluster {name}")
            _remove_from_file(state, name, owner)
        return
    if deletion_protected(cl):
        raise CliExit(ExitCode.BLOCKED, protection_message(name), topic="safety")

    for line in _delete_details(client, pid, cl, discard_snapshots):
        out(line)
    if not console.confirm_typed(state, "Type the cluster name to confirm deletion", "delete a cluster", name):
        out("Cancelled; nothing was deleted.")
        return

    note(f"→ deleting cluster {name} …")
    if is_free(cl):
        ep.delete_free_cluster(client, pid, str(cl["id"]))
    else:
        ep.delete_cluster(client, pid, str(cl["id"]), retain_snapshot_backups=not discard_snapshots)
    if state.no_wait:
        out(f"cluster {name} is being deleted (--no-wait); run this command again to wait until it is gone")
        return
    _wait_gone(state, client, pid, cl)
    if is_free(cl):
        out(f"deleted cluster {name}")
    else:
        out(f"deleted cluster {name} (snapshot backups {'deleted' if discard_snapshots else 'retained'})")
    _remove_from_file(state, name, owner)
