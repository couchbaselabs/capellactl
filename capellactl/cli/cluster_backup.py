"""cluster backup …: cloud snapshot backups of a whole cluster.

`schedule show | options | set | delete` (CAP-056): set and delete record `backupSchedule` in capella.yaml and apply
it, like the hibernation schedule. `list | create | retain | delete | restore | restores | regions` (CAP-057) act on
the backups themselves; they write nothing to capella.yaml.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from typing import Any

import click
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from capellactl.api import endpoints as ep
from capellactl.api.errors import Forbidden, NotFound
from capellactl.cli import console
from capellactl.cli.backup_common import DONE, FAILED, parse_hours, progress, refuse_free, size_text, when
from capellactl.cli.cluster_ops import change_and_apply, locate, open_editor
from capellactl.cli.console import note, out, wait_progress
from capellactl.cli.env import pass_state
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.groups import SuggestingGroup
from capellactl.cli.resource_cmds import (
    _file_org,
    _list_table,
    _project_id,
    complete_cluster_names,
    live_cluster,
    pick_project,
    project_of_cluster,
)
from capellactl.cli.state import AppState
from capellactl.config.editor import ConfigEditor, put, to_commented
from capellactl.engine.clock import get_clock
from capellactl.engine.waiter import (
    StatusFailed,
    StatusTimeout,
    WaitFailed,
    WaitTimeout,
    wait_for_cluster,
    wait_for_status,
)
from capellactl.output.render import dumps
from capellactl.resources.backup_schedule import hours_text, options_problem, snapshot_summary, start_hm

PROJECT_OPT = click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name "
                                                             "repeats).")
NAME_ARG = click.argument("name", shell_complete=complete_cluster_names)


@click.group("backup", cls=SuggestingGroup, epilog="\b\nExamples:\n"
             "  capellactl cluster backup schedule set nova-prod-01 --every 24 --retain 30d\n"
             "  capellactl cluster backup list nova-prod-01\n"
             "  capellactl cluster backup create nova-prod-01\n"
             "  capellactl cluster backup restore nova-prod-01 BACKUP_ID\n"
             "Backups of one bucket: capellactl bucket backup --help. Both kinds: capellactl help backup")
def backup() -> None:
    """Cluster backups (cloud snapshots of the whole cluster): schedule, list, create, retain, delete, restore."""


@backup.group("schedule", cls=SuggestingGroup, epilog="\b\nExamples:\n"
              "  capellactl cluster backup schedule options nova-prod-01\n"
              "  capellactl cluster backup schedule set nova-prod-01 --every 24 --retain 30d\n"
              "  capellactl cluster backup schedule set nova-prod-01 --start 02:00 --copy-to us-west-2\n"
              "  capellactl cluster backup schedule show nova-prod-01\n"
              "  capellactl cluster backup schedule delete nova-prod-01")
def schedule() -> None:
    """When the cluster is backed up and how long backups are kept (recorded in capella.yaml)."""


def _live(state: AppState, name: str, project: str | None) -> tuple[Any, str, dict[str, Any]]:
    client, pid, cl = live_cluster(state, name, project)
    refuse_free(cl)
    return client, pid, cl


def next_backup(body: dict[str, Any], now: datetime) -> datetime | None:
    """The next scheduled backup after `now`: startTime plus whole intervals."""
    try:
        start = datetime.fromisoformat(str(body.get("startTime")).replace("Z", "+00:00"))
        step = timedelta(hours=int(body.get("interval") or 0))
    except (TypeError, ValueError):
        return None
    if not step or start.tzinfo is None:
        return None
    now = now.astimezone(timezone.utc)
    if start > now:
        return start
    return start + step * ((now - start) // step + 1)


# --------------------------------------------------------------- schedule show
@schedule.command("show", epilog="\b\nExamples:\n  capellactl cluster backup schedule show nova-prod-01\n"
                                 "  capellactl -o json cluster backup schedule show nova-prod-01")
@NAME_ARG
@PROJECT_OPT
@pass_state
def schedule_show(state: AppState, name: str, project: str | None) -> None:
    """Show the cluster's backup schedule and the next backup (CAP-056 AC4)."""
    client, pid, cl = _live(state, name, project)
    body = ep.get_snapshot_schedule(client, pid, str(cl["id"]))
    nxt = next_backup(body, get_clock().now()) if body else None
    if state.json:
        out(dumps({"cluster": name, **(body or {}), **({"nextBackup": nxt.strftime("%Y-%m-%dT%H:%M:%SZ")} if nxt else {})}))
        return
    if not body:
        out(f"cluster {name} has no backup schedule; set one with 'capellactl cluster backup schedule set {name} "
            "--every HOURS --retain DAYSd'")
        return
    out(snapshot_summary(body))
    if nxt:
        out(f"next backup: {nxt.strftime('%Y-%m-%d %H:%M')} UTC")


# ------------------------------------------------------------ schedule options
@schedule.command("options", epilog="\b\nExamples:\n  capellactl cluster backup schedule options nova-prod-01")
@NAME_ARG
@PROJECT_OPT
@pass_state
def schedule_options(state: AppState, name: str, project: str | None) -> None:
    """What the cluster's support plan permits: backup intervals, retention range and copy regions (CAP-056 AC4)."""
    client, pid, cl = _live(state, name, project)
    options = ep.get_snapshot_schedule_options(client, pid, str(cl["id"]))
    regions = ep.list_snapshot_regions(client, pid, str(cl["id"]))
    if state.json:
        out(dumps({"cluster": name, **options, "regions": regions}))
        return
    plan = (cl.get("support") or {}).get("plan", "?")
    out(f"Cluster backup schedule options for {name} (support plan: {plan})")
    out(f"  every (hours)   {', '.join(str(i) for i in options.get('intervals') or [])}")
    out(f"  keep            {hours_text(options.get('minimumRetention') or 0)} to "
        f"{hours_text(options.get('maximumRetention') or 0)}")
    out(f"  copy regions    {', '.join(regions) + ' (up to two)' if regions else 'none (AWS and Azure only)'}")


# ----------------------------------------------------------------- schedule set
@schedule.command("set", epilog="\b\nExamples:\n"
                  "  capellactl cluster backup schedule set nova-prod-01 --every 24 --retain 30d\n"
                  "  capellactl cluster backup schedule set nova-prod-01 --every 6 --retain 7d --start 02:00 "
                  "--copy-to us-west-2\n"
                  "  capellactl cluster backup schedule set nova-prod-01 --retain 90d     (change one value)\n"
                  "Permitted values: capellactl cluster backup schedule options NAME")
@NAME_ARG
@click.option("--every", type=int, metavar="HOURS", help="Hours between backups (needed for a new schedule).")
@click.option("--retain", metavar="DURATION", help="How long each backup is kept: hours or days, e.g. 720, 720h, "
                                                   "30d (needed for a new schedule).")
@click.option("--start", metavar="HH:MM", help="Time of day (UTC) of the first backup.")
@click.option("--copy-to", "copy_to", multiple=True, metavar="REGION", help="Also keep a copy in this region "
                                                                             "(repeatable; at most two).")
@click.option("--no-copies", is_flag=True, help="Stop keeping copies in other regions.")
@PROJECT_OPT
@click.option("--no-apply", is_flag=True, help="Only record the schedule in capella.yaml; apply later.")
@pass_state
def schedule_set(state: AppState, name: str, every: int | None, retain: str | None, start: str | None,
                 copy_to: tuple[str, ...], no_copies: bool, project: str | None, no_apply: bool) -> None:
    """Create or change the backup schedule: records it in capella.yaml and applies it (CAP-056 AC1)."""
    ed = open_editor(state)
    _, cl = locate(ed, name, project_of_cluster(state, name, project))
    if cl.get("tier") == "free":
        raise CliExit(ExitCode.BLOCKED, "free-tier clusters have no backups; create a provisioned cluster for data "
                                        "that needs them", topic="backup")
    if every is None and retain is None and start is None and not copy_to and not no_copies:
        raise CliExit(ExitCode.CONFIG_INVALID, "pass at least one of --every, --retain, --start, --copy-to or "
                                               "--no-copies", topic="backup")
    if start is not None and start_hm(start) != start:
        raise CliExit(ExitCode.CONFIG_INVALID, f"--start takes a UTC time of day HH:MM, e.g. 02:00 (got '{start}')",
                      topic="backup")
    current = cl.get("backupSchedule")
    new = not isinstance(current, CommentedMap) or current.get("ensure") == "absent"
    if new and (every is None or retain is None):
        raise CliExit(ExitCode.CONFIG_INVALID, "a new backup schedule needs --every HOURS and --retain DURATION "
                                               f"(permitted values: capellactl cluster backup schedule options {name})",
                      topic="backup")
    values: dict[str, Any] = {} if new else {k: v for k, v in dict(current).items() if k != "ensure"}
    if every is not None:
        values["interval"] = every
    if retain is not None:
        values["retention"] = parse_hours(retain, "--retain")
    if start is not None:
        values["startTime"] = DoubleQuotedScalarString(start)
    if copy_to:
        values["copyToRegions"] = list(copy_to)
    elif no_copies:
        values.pop("copyToRegions", None)
    _check_permitted(state, name, project, values)
    node = to_commented({k: v for k, v in values.items() if k != "copyToRegions"}, "backupSchedule")
    if values.get("copyToRegions"):
        node["copyToRegions"] = to_commented(values["copyToRegions"], "copyToRegions")
    put(cl, "backupSchedule", node)
    change_and_apply(state, ed, f"backup-schedule/{name}",
                     f"Record this backup schedule in capella.yaml and apply it to {name}?", no_apply,
                     noop_message=f"backup schedule of {name} already matches; capella.yaml is up to date")


def _check_permitted(state: AppState, name: str, project: str | None, values: dict[str, Any]) -> None:
    """Refuse values the support plan does not permit before anything is written (CAP-056 AC3)."""
    try:
        client, pid, cl = live_cluster(state, name, project)
    except CliExit as exc:
        if exc.code is ExitCode.ERROR:  # not deployed yet: Capella checks it when the cluster is applied
            return
        raise
    try:
        options = ep.get_snapshot_schedule_options(client, pid, str(cl["id"]))
        regions = ep.list_snapshot_regions(client, pid, str(cl["id"])) if values.get("copyToRegions") else None
    except (NotFound, Forbidden):
        return
    problem = options_problem(options, values, regions)
    if problem:
        raise CliExit(ExitCode.CONFIG_INVALID, f"{problem} (see 'capellactl cluster backup schedule options {name}')",
                      topic="backup")


# -------------------------------------------------------------- schedule delete
@schedule.command("delete", epilog="\b\nExamples:\n  capellactl cluster backup schedule delete nova-prod-01")
@NAME_ARG
@PROJECT_OPT
@pass_state
def schedule_delete(state: AppState, name: str, project: str | None) -> None:
    """Delete the backup schedule in Capella and remove it from capella.yaml; existing backups are kept (AC5)."""
    owner = project_of_cluster(state, name, project)
    client, pid, cl = _live(state, name, project)
    body = ep.get_snapshot_schedule(client, pid, str(cl["id"]))
    if body:
        out(f"  - backup schedule {name}  {snapshot_summary(body)}")
        if not console.confirm(state, f"Delete the backup schedule of {name}? Existing backups are kept until they "
                                      "expire.", "delete the backup schedule"):
            out("Cancelled; the backup schedule is unchanged.")
            return
        ep.delete_snapshot_schedule(client, pid, str(cl["id"]))
        out(f"deleted the backup schedule of {name}")
    else:
        out(f"cluster {name} has no backup schedule; nothing to do in Capella")
    path = state.config_path()
    if path.exists():
        ed = ConfigEditor(path)
        try:
            found = ed.find_cluster(name, owner)
        except LookupError:
            found = None
        if found is not None and "backupSchedule" in found[1]:
            del found[1]["backupSchedule"]
            saved = ed.save()
            note(f"{path.name} updated: backupSchedule removed for {name} (previous version kept as {saved.name})")


# ------------------------------------------------------------------------ list
def _snapshot_rows(items: list[dict[str, Any]]) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = [("CREATED", "TYPE", "STATUS", "SIZE", "EXPIRES", "COPIES", "ID")]
    for s in sorted(items, key=lambda s: str(s.get("createdAt")), reverse=True):
        copies = ", ".join(str(c.get("regionCode")) for c in s.get("crossRegionCopies") or []) or "-"
        rows.append((when(s.get("createdAt")), str(s.get("type", "")), str((s.get("progress") or {}).get("status", "")),
                     size_text(s.get("databaseSize")), when(s.get("expiration")), copies, str(s.get("id"))))
    return rows


@backup.command("list", epilog="\b\nExamples:\n  capellactl cluster backup list nova-prod-01\n"
                                "  capellactl cluster backup list                 (every cluster of the project)\n"
                                "  capellactl -o json cluster backup list nova-prod-01")
@click.argument("name", required=False, shell_complete=complete_cluster_names)
@PROJECT_OPT
@pass_state
def backup_list(state: AppState, name: str | None, project: str | None) -> None:
    """List a cluster's backups, newest first; without NAME, the newest and oldest of each cluster (CAP-057 AC1)."""
    if name is None:
        client = state.client(_file_org(state))
        pid, _ = _project_id(state, client, pick_project(state, project)[0])
        items = ep.list_project_snapshots(client, pid)
        if state.json:
            out(dumps(items))
            return
        if not items:
            out("no backups")
            return
        rows: list[tuple[str, ...]] = [("CLUSTER", "REGION", "NEWEST", "OLDEST", "CLUSTER ID")]
        for c in sorted(items, key=lambda c: str(c.get("clusterName"))):
            rows.append((str(c.get("clusterName")), str(c.get("region", "")),
                         when((c.get("mostRecentSnapshot") or {}).get("createdAt")),
                         when((c.get("oldestSnapshot") or {}).get("createdAt")), str(c.get("clusterId"))))
        out(_list_table(rows))
        return
    client, pid, cl = _live(state, name, project)
    items = ep.list_snapshots(client, pid, str(cl["id"]))
    if state.json:
        out(dumps(items))
        return
    out(_list_table(_snapshot_rows(items)) if items else "no backups")


def _find_snapshot(client: Any, pid: str, cid: str, backup_id: str) -> dict[str, Any] | None:
    return next((s for s in ep.list_snapshots(client, pid, cid) if s.get("id") == backup_id), None)


# ---------------------------------------------------------------------- create
@backup.command("create", epilog="\b\nExamples:\n  capellactl cluster backup create nova-prod-01\n"
                                  "  capellactl cluster backup create nova-prod-01 --retain 7d --copy-to us-west-2\n"
                                  "  capellactl --no-wait cluster backup create nova-prod-01")
@NAME_ARG
@click.option("--retain", metavar="DURATION", help="How long to keep it: hours or days, e.g. 168 or 7d (default: "
                                                   "Capella's).")
@click.option("--copy-to", "copy_to", multiple=True, metavar="REGION", help="Also keep a copy in this region "
                                                                             "(repeatable; at most two).")
@PROJECT_OPT
@pass_state
def backup_create(state: AppState, name: str, retain: str | None, copy_to: tuple[str, ...], project: str | None) -> None:
    """Back the cluster up now and wait until the backup is complete (CAP-057 AC2)."""
    client, pid, cl = _live(state, name, project)
    cid = str(cl["id"])
    body: dict[str, Any] = {}
    if retain is not None:
        body["retention"] = parse_hours(retain, "--retain")
    if copy_to:
        regions = ep.list_snapshot_regions(client, pid, cid)
        problem = options_problem({}, {"interval": 0, "retention": 0, "copyToRegions": list(copy_to)}, regions)
        if problem:
            raise CliExit(ExitCode.CONFIG_INVALID, problem, topic="backup")
        body["regionsToCopy"] = list(copy_to)
    note(f"→ backing up cluster {name} …")
    backup_id = ep.create_snapshot(client, pid, cid, body)
    if state.no_wait:
        out(f"backup {backup_id} of {name} started (--no-wait); see it with 'capellactl cluster backup list {name}'")
        return

    def status() -> str | None:
        found = _find_snapshot(client, pid, cid, backup_id)
        return str((found.get("progress") or {}).get("status")) if found else None

    try:
        wait_for_status(status, DONE, FAILED, state.timeout, get_clock(), f"backup {backup_id} of {name}",
                        progress(f"backup of {name}"))
    except StatusFailed as exc:
        raise CliExit(ExitCode.ERROR, f"Failed: {exc}", topic="backup") from None
    except StatusTimeout as exc:
        raise CliExit(ExitCode.TIMEOUT, str(exc)) from None
    out(f"backup {backup_id} of {name} is complete")


# ---------------------------------------------------------------------- retain
@backup.command("retain", epilog="\b\nExamples:\n  capellactl cluster backup retain nova-prod-01 BACKUP_ID --retain 90d")
@NAME_ARG
@click.argument("backup_id", metavar="BACKUP_ID")
@click.option("--retain", required=True, metavar="DURATION", help="How long to keep it, counted from when it was "
                                                                  "taken: hours or days, e.g. 2160 or 90d.")
@PROJECT_OPT
@pass_state
def backup_retain(state: AppState, name: str, backup_id: str, retain: str, project: str | None) -> None:
    """Keep one backup longer (or shorter) (CAP-057 AC3)."""
    hours = parse_hours(retain, "--retain")
    client, pid, cl = _live(state, name, project)
    found = _find_snapshot(client, pid, str(cl["id"]), backup_id)
    if found is None:
        raise CliExit(ExitCode.ERROR, f"backup {backup_id} of {name} not found; list them with 'capellactl cluster "
                                      f"backup list {name}'")
    if int(found.get("retention") or 0) == hours:
        out(f"No changes: backup {backup_id} is already kept {hours_text(hours)}.")
        return
    ep.update_snapshot_retention(client, pid, str(cl["id"]), backup_id, hours)
    out(f"backup {backup_id} of {name} is now kept {hours_text(hours)} (was {hours_text(found.get('retention') or 0)})")


# ---------------------------------------------------------------------- delete
@backup.command("delete", epilog="\b\nExamples:\n  capellactl cluster backup delete nova-prod-01 BACKUP_ID")
@NAME_ARG
@click.argument("backup_id", metavar="BACKUP_ID")
@PROJECT_OPT
@pass_state
def backup_delete(state: AppState, name: str, backup_id: str, project: str | None) -> None:
    """Delete one backup of the cluster (CAP-057 AC4)."""
    client, pid, cl = _live(state, name, project)
    found = _find_snapshot(client, pid, str(cl["id"]), backup_id)
    if found is None:
        out(f"backup {backup_id} of {name} not found, nothing to do")
        return
    out(f"  - backup {backup_id} of {name}  taken {when(found.get('createdAt'))} UTC · "
        f"{size_text(found.get('databaseSize'))}")
    if not console.confirm_typed(state, "Type the cluster name to confirm deletion", "delete a backup", name):
        out("Cancelled; nothing was deleted.")
        return
    with contextlib.suppress(NotFound):
        ep.delete_snapshot(client, pid, str(cl["id"]), backup_id)
    out(f"deleted backup {backup_id} of {name}")


# --------------------------------------------------------------------- restore
@backup.command("restore", epilog="\b\nExamples:\n  capellactl cluster backup restore nova-prod-01 BACKUP_ID\n"
                                   "  capellactl cluster backup restore nova-prod-01 BACKUP_ID --from-region us-west-2")
@NAME_ARG
@click.argument("backup_id", metavar="BACKUP_ID")
@click.option("--from-region", "from_region", multiple=True, metavar="REGION",
              help="Restore from the copy in this region if the original is not restorable (repeatable, in order).")
@PROJECT_OPT
@pass_state
def backup_restore(state: AppState, name: str, backup_id: str, from_region: tuple[str, ...],
                   project: str | None) -> None:
    """Replace all data of the cluster with a backup, and wait until the cluster is healthy (CAP-057 AC5)."""
    client, pid, cl = _live(state, name, project)
    cid = str(cl["id"])
    if cl.get("currentState") in ("turnedOff", "turningOff"):
        raise CliExit(ExitCode.BLOCKED, f"cluster {name} is turned off; power it on before restoring "
                                        f"('capellactl cluster power {name} --on')", topic="hibernation")
    found = _find_snapshot(client, pid, cid, backup_id)
    if found is None:
        raise CliExit(ExitCode.ERROR, f"backup {backup_id} of {name} not found; list them with 'capellactl cluster "
                                      f"backup list {name}'")
    out(f"  ± cluster {name}  all data is replaced with the backup of {when(found.get('createdAt'))} UTC")
    if not console.confirm_typed(state, "Type the cluster name to confirm the restore", "restore a cluster", name):
        out("Cancelled; nothing was restored.")
        return
    note(f"→ restoring cluster {name} …")
    restore_id = ep.restore_snapshot(client, pid, cid, backup_id,
                                     {"crossRegionRestorePreference": list(from_region)} if from_region else {})
    if state.no_wait:
        out(f"restore {restore_id} of {name} started (--no-wait); follow it with 'capellactl cluster backup restores "
            f"{name}'")
        return

    def status() -> str | None:
        found_ = next((r for r in ep.list_snapshot_restores(client, pid, cid) if r.get("id") == restore_id), None)
        return str(found_.get("status")) if found_ else None

    try:
        wait_for_status(status, DONE, FAILED, state.timeout, get_clock(), f"restore of {name}",
                        progress(f"restore of {name}"))
        on_state, on_tick = wait_progress(f"cluster {name}")
        wait_for_cluster(client, pid, cid, "ready", state.timeout, get_clock(), on_state, name=name, on_tick=on_tick)
    except (StatusFailed, WaitFailed) as exc:
        raise CliExit(ExitCode.ERROR, f"Failed: {exc}", topic="backup") from None
    except (StatusTimeout, WaitTimeout) as exc:
        raise CliExit(ExitCode.TIMEOUT, str(exc)) from None
    out(f"restored cluster {name} from the backup of {when(found.get('createdAt'))} UTC")


# -------------------------------------------------------------------- restores
@backup.command("restores", epilog="\b\nExamples:\n  capellactl cluster backup restores nova-prod-01")
@NAME_ARG
@PROJECT_OPT
@pass_state
def backup_restores(state: AppState, name: str, project: str | None) -> None:
    """List the restores of the cluster (CAP-057 AC6)."""
    client, pid, cl = _live(state, name, project)
    items = ep.list_snapshot_restores(client, pid, str(cl["id"]))
    if state.json:
        out(dumps(items))
        return
    rows: list[tuple[str, ...]] = [("STARTED", "FINISHED", "SNAPSHOT", "STATUS", "ID")]
    for r in sorted(items, key=lambda r: str(r.get("createdAt")), reverse=True):
        rows.append((when(r.get("createdAt")), when(r.get("restoreEnd")) or "-", when(r.get("snapshot")),
                     str(r.get("status", "")), str(r.get("id"))))
    out(_list_table(rows) if items else "no restores")


# --------------------------------------------------------------------- regions
@backup.command("regions", epilog="\b\nExamples:\n  capellactl cluster backup regions nova-prod-01")
@NAME_ARG
@PROJECT_OPT
@pass_state
def backup_regions(state: AppState, name: str, project: str | None) -> None:
    """List the regions where copies of the cluster's backups can be kept (AWS and Azure) (CAP-057 AC6)."""
    client, pid, cl = _live(state, name, project)
    regions = ep.list_snapshot_regions(client, pid, str(cl["id"]))
    if state.json:
        out(dumps(regions))
        return
    out(_list_table([("REGION",), *((r,) for r in regions)]) if regions else "no copy regions (AWS and Azure only)")
