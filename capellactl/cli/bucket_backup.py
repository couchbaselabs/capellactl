"""bucket backup …: backups of one bucket.

`schedule show | set | delete` and `cycle list | get` (CAP-058): set and delete record `backupSchedule` under the
bucket in capella.yaml and apply it. `list | get | create | delete | restore | export` (CAP-059) act on the backups
themselves; they write nothing to capella.yaml.
"""

from __future__ import annotations

import contextlib
from typing import Any

import click
from ruamel.yaml.comments import CommentedMap

from capellactl.api import endpoints as ep
from capellactl.api.errors import Conflict, NotFound, ValidationFailed
from capellactl.cli import console
from capellactl.cli.backup_common import DONE, FAILED, progress, refuse_free, when
from capellactl.cli.bucket_cmds import _bucket_node, _find_bucket
from capellactl.cli.cluster_ops import change_and_apply, locate, open_editor
from capellactl.cli.console import note, out
from capellactl.cli.env import pass_state
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.groups import SuggestingGroup
from capellactl.cli.resource_cmds import (
    _list_table,
    complete_cluster_names,
    find_cluster,
    live_cluster,
    project_of_cluster,
)
from capellactl.cli.state import AppState
from capellactl.config.editor import BUCKET_KEY_ORDER, ConfigEditor, put, to_commented
from capellactl.engine.clock import get_clock
from capellactl.engine.waiter import StatusFailed, StatusTimeout, wait_for_status
from capellactl.output.render import dumps
from capellactl.resources.backup_schedule import BUCKET_DEFAULTS, RETENTION_WORDS, bucket_summary

PROJECT_OPT = click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name "
                                                             "repeats).")
CLUSTER_ARG = click.argument("cluster", shell_complete=complete_cluster_names)
DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
INCREMENTS = [1, 2, 4, 6, 8, 12, 24]


@click.group("backup", cls=SuggestingGroup, epilog="\b\nExamples:\n"
             "  capellactl bucket backup schedule set nova-prod-01 orders\n"
             "  capellactl bucket backup list nova-prod-01\n"
             "  capellactl bucket backup create nova-prod-01 orders\n"
             "  capellactl bucket backup restore nova-prod-01 BACKUP_ID --replace-ttl none\n"
             "Backups of the whole cluster: capellactl cluster backup --help. Both kinds: capellactl help backup")
def backup() -> None:
    """Bucket backups (weekly full + incremental): schedule, cycles, list, get, create, delete, restore, export."""


@backup.group("schedule", cls=SuggestingGroup, epilog="\b\nExamples:\n"
              "  capellactl bucket backup schedule set nova-prod-01 orders\n"
              "  capellactl bucket backup schedule set nova-prod-01 orders --day sunday --start-at 2 "
              "--incremental-every 12 --retention 90days\n"
              "  capellactl bucket backup schedule show nova-prod-01 orders\n"
              "  capellactl bucket backup schedule delete nova-prod-01 orders")
def schedule() -> None:
    """When a bucket is backed up and how long backups are kept (recorded in capella.yaml)."""


@backup.group("cycle", cls=SuggestingGroup, epilog="\b\nExamples:\n"
              "  capellactl bucket backup cycle list nova-prod-01 orders\n"
              "  capellactl bucket backup cycle get nova-prod-01 orders CYCLE_ID")
def cycle() -> None:
    """Backup cycles: a weekly full backup and the incrementals that follow it."""


def _live_bucket(state: AppState, cluster: str, name: str, project: str | None) -> tuple[Any, str, dict[str, Any], str]:
    """(client, project id, cluster, bucket id) of a bucket that exists in Capella."""
    client, pid, cl = live_cluster(state, cluster, project)
    refuse_free(cl)
    b = _find_bucket(client, pid, cl, name)
    if b is None:
        raise CliExit(ExitCode.ERROR, f"bucket {name} not found in cluster {cluster}",
                                      action=f"Check the name with 'capellactl bucket list {cluster}'.")
    return client, pid, cl, str(b["id"])


def _live(state: AppState, cluster: str, project: str | None) -> tuple[Any, str, dict[str, Any]]:
    client, pid, cl = live_cluster(state, cluster, project)
    refuse_free(cl)
    return client, pid, cl


def _backup_rows(items: list[dict[str, Any]], bucket: bool = True) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = [(*(("BUCKET",) if bucket else ()), "DATE", "METHOD", "SOURCE", "STATUS", "SIZE",
                                    "ITEMS", "EXPIRES", "ID")]
    for b in sorted(items, key=lambda b: str(b.get("date")), reverse=True):
        stats = b.get("stats") or {}
        size = stats.get("sizeInMb")
        rows.append((*((str(b.get("bucketName")),) if bucket else ()), when(b.get("date")), str(b.get("method", "")),
                     str(b.get("source", "")), str(b.get("status", "")),
                     f"{size / 1024:.1f} GB" if isinstance(size, (int, float)) and size >= 1024 else
                     (f"{size:.0f} MB" if isinstance(size, (int, float)) else ""),
                     f"{int(stats.get('items') or 0):,}", when(b.get("restoreBefore")), str(b.get("id"))))
    return rows


# --------------------------------------------------------------- schedule show
@schedule.command("show", epilog="\b\nExamples:\n  capellactl bucket backup schedule show nova-prod-01 orders\n"
                                 "  capellactl -o json bucket backup schedule show nova-prod-01 orders")
@CLUSTER_ARG
@click.argument("bucket")
@PROJECT_OPT
@pass_state
def schedule_show(state: AppState, cluster: str, bucket: str, project: str | None) -> None:
    """Show a bucket's backup schedule."""
    client, pid, cl, bid = _live_bucket(state, cluster, bucket, project)
    try:
        body: dict[str, Any] | None = ep.get_bucket_backup_schedule(client, pid, str(cl["id"]), bid)
    except NotFound:
        body = None
    if state.json:
        out(dumps({"cluster": cluster, "bucket": bucket, **(body or {})}))
        return
    if not body:
        out(f"bucket {bucket} has no backup schedule; set one with 'capellactl bucket backup schedule set {cluster} "
            f"{bucket}'")
        return
    out(bucket_summary(body.get("weeklySchedule") or {}))


# ---------------------------------------------------------------- schedule set
@schedule.command("set", epilog="\b\nExamples:\n"
                  "  capellactl bucket backup schedule set nova-prod-01 orders\n"
                  "  capellactl bucket backup schedule set nova-prod-01 orders --day sunday --start-at 2 "
                  "--incremental-every 12 --retention 90days\n"
                  "  capellactl bucket backup schedule set nova-prod-01 orders --retention 1year   (change one value)\n"
                  "Defaults for a new schedule: sunday, 0 (UTC), every 24 h, 30days, not cost-optimized.")
@CLUSTER_ARG
@click.argument("bucket")
@click.option("--day", metavar="DAY", help=f"Day of the weekly full backup: {', '.join(DAYS)}.")
@click.option("--start-at", type=int, metavar="HOUR", help="Hour (UTC, 0–23) the backups start.")
@click.option("--incremental-every", type=int, metavar="HOURS",
              help=f"Hours between incremental backups: {', '.join(map(str, INCREMENTS))}.")
@click.option("--retention", metavar="TIME", help=f"How long backups are kept: {', '.join(RETENTION_WORDS)}.")
@click.option("--cost-optimized/--no-cost-optimized", default=None, help="Capella's cost-optimized retention.")
@PROJECT_OPT
@click.option("--no-apply", is_flag=True, help="Only record the schedule in capella.yaml; apply later.")
@pass_state
def schedule_set(state: AppState, cluster: str, bucket: str, day: str | None, start_at: int | None,
                 incremental_every: int | None, retention: str | None, cost_optimized: bool | None,
                 project: str | None, no_apply: bool) -> None:
    """Create or change a bucket's backup schedule: records it in capella.yaml and applies it."""
    ed = open_editor(state)
    proj, cl = locate(ed, cluster, project_of_cluster(state, cluster, project))
    if cl.get("tier") == "free":
        raise CliExit(ExitCode.BLOCKED, "free-tier clusters have no backups", topic="backup",
                                        action="Create a provisioned cluster for data that needs backups "
                                               "('capellactl cluster create NAME').")
    node = _bucket_node(cl, bucket)
    if node is None:
        raise CliExit(ExitCode.ERROR, f"bucket {bucket} is not in capella.yaml for {cluster}",
                                      action=f"Create it with 'capellactl bucket create {cluster} {bucket}', or run "
                                             f"'capellactl sync' if it exists in Capella.")
    current = node.get("backupSchedule")
    new = not isinstance(current, CommentedMap) or current.get("ensure") == "absent"
    given = {"dayOfWeek": day, "startAt": start_at, "incrementalEvery": incremental_every,
             "retentionTime": retention, "costOptimizedRetention": cost_optimized}
    values = dict(BUCKET_DEFAULTS) if new else {**BUCKET_DEFAULTS, **{k: v for k, v in dict(current).items()
                                                                      if k in BUCKET_DEFAULTS}}
    if new and all(v is None for v in given.values()) and console.is_interactive():
        out("Press Enter to keep the default.")
        given = {"dayOfWeek": console.ask("Day of the weekly full backup", values["dayOfWeek"],
                                          type=click.Choice(DAYS)),
                 "startAt": console.ask("Hour (UTC) the backups start", values["startAt"], type=click.IntRange(0, 23)),
                 "incrementalEvery": console.ask("Hours between incremental backups", values["incrementalEvery"],
                                                 type=click.Choice([str(i) for i in INCREMENTS])),
                 "retentionTime": console.ask("Keep backups for", values["retentionTime"],
                                              type=click.Choice(list(RETENTION_WORDS))),
                 "costOptimizedRetention": console.ask_yes_no("Cost-optimized retention?",
                                                              bool(values["costOptimizedRetention"]))}
        given["incrementalEvery"] = int(str(given["incrementalEvery"]))
    values.update({k: v for k, v in given.items() if v is not None})
    put(node, "backupSchedule", to_commented(values, "backupSchedule"), order=BUCKET_KEY_ORDER)
    change_and_apply(state, ed, f"bucket-backup-schedule/{cluster}/{bucket}",
                     f"Record this backup schedule in capella.yaml and apply it to bucket {bucket}?", no_apply,
                     noop_message=f"backup schedule of {bucket} already matches; capella.yaml is up to date")


# ------------------------------------------------------------- schedule delete
@schedule.command("delete", epilog="\b\nExamples:\n  capellactl bucket backup schedule delete nova-prod-01 orders")
@CLUSTER_ARG
@click.argument("bucket")
@PROJECT_OPT
@pass_state
def schedule_delete(state: AppState, cluster: str, bucket: str, project: str | None) -> None:
    """Delete a bucket's backup schedule and remove it from capella.yaml; existing backups are kept."""
    owner = project_of_cluster(state, cluster, project)
    client, pid, cl, bid = _live_bucket(state, cluster, bucket, project)
    try:
        body: dict[str, Any] | None = ep.get_bucket_backup_schedule(client, pid, str(cl["id"]), bid)
    except NotFound:
        body = None
    if body:
        out(f"  - backup schedule {cluster}/{bucket}  {bucket_summary(body.get('weeklySchedule') or {})}")
        if not console.confirm(state, f"Delete the backup schedule of {bucket}? Existing backups are kept until they "
                                      "expire.", "delete the backup schedule"):
            out("Cancelled; the backup schedule is unchanged.")
            return
        ep.delete_bucket_backup_schedule(client, pid, str(cl["id"]), bid)
        out(f"deleted the backup schedule of {bucket}")
    else:
        out(f"bucket {bucket} has no backup schedule; nothing to do in Capella")
    path = state.config_path()
    if path.exists():
        ed = ConfigEditor(path)
        try:
            found = ed.find_cluster(cluster, owner)
        except LookupError:
            found = None
        node = _bucket_node(found[1], bucket) if found is not None else None
        if node is not None and "backupSchedule" in node:
            del node["backupSchedule"]
            saved = ed.save()
            note(f"{path.name} updated: backupSchedule removed for bucket {bucket} (previous version kept as "
                 f"{saved.name})")


# ---------------------------------------------------------------------- cycles
@cycle.command("list", epilog="\b\nExamples:\n  capellactl bucket backup cycle list nova-prod-01 orders")
@CLUSTER_ARG
@click.argument("bucket")
@PROJECT_OPT
@pass_state
def cycle_list(state: AppState, cluster: str, bucket: str, project: str | None) -> None:
    """List a bucket's backup cycles, newest first."""
    client, pid, cl, bid = _live_bucket(state, cluster, bucket, project)
    cycles = ep.list_backup_cycles(client, pid, str(cl["id"]), bid)
    if state.json:
        out(dumps(cycles))
        return
    rows: list[tuple[str, ...]] = [("STARTED", "BACKUPS", "LATEST STATUS", "ID")]
    for c in sorted(cycles, key=lambda c: str(c.get("createdAt")), reverse=True):
        backups = ep.list_cycle_backups(client, pid, str(cl["id"]), bid, str(c.get("cycleID")))
        latest = max(backups, key=lambda b: str(b.get("date")), default={})
        rows.append((when(c.get("createdAt")), str(len(backups)), str(latest.get("status", "-")), str(c.get("cycleID"))))
    out(_list_table(rows) if cycles else "no backup cycles")


@cycle.command("get", epilog="\b\nExamples:\n  capellactl bucket backup cycle get nova-prod-01 orders CYCLE_ID")
@CLUSTER_ARG
@click.argument("bucket")
@click.argument("cycle_id", metavar="CYCLE_ID")
@PROJECT_OPT
@pass_state
def cycle_get(state: AppState, cluster: str, bucket: str, cycle_id: str, project: str | None) -> None:
    """List the backups of one cycle: full and incremental, scheduled and on-demand."""
    client, pid, cl, bid = _live_bucket(state, cluster, bucket, project)
    try:
        items = ep.list_cycle_backups(client, pid, str(cl["id"]), bid, cycle_id)
    except NotFound:
        raise CliExit(ExitCode.ERROR, f"cycle {cycle_id} of {bucket} not found",
                                      action=f"List them with 'capellactl bucket backup cycle list {cluster} "
                                             f"{bucket}'.") from None
    out(dumps(items) if state.json else _list_table(_backup_rows(items, bucket=False)))


# ------------------------------------------------------------------- list, get
def _bucket_backups(client: Any, pid: str, cid: str, bid: str) -> list[dict[str, Any]]:
    """Every backup of a bucket, across its cycles."""
    return [b for c in ep.list_backup_cycles(client, pid, cid, bid)
            for b in ep.list_cycle_backups(client, pid, cid, bid, str(c.get("cycleID")))]


@backup.command("list", epilog="\b\nExamples:\n  capellactl bucket backup list nova-prod-01          (the latest of "
                               "each bucket)\n  capellactl bucket backup list nova-prod-01 orders   (every backup of "
                               "orders)")
@CLUSTER_ARG
@click.argument("bucket", required=False)
@PROJECT_OPT
@pass_state
def backup_list(state: AppState, cluster: str, bucket: str | None, project: str | None) -> None:
    """List bucket backups: the latest of each bucket, or every backup of BUCKET."""
    if bucket is None:
        client, pid, cl = _live(state, cluster, project)
        items = ep.list_cluster_backups(client, pid, str(cl["id"]))
    else:
        client, pid, cl, bid = _live_bucket(state, cluster, bucket, project)
        items = _bucket_backups(client, pid, str(cl["id"]), bid)
    if state.json:
        out(dumps(items))
        return
    out(_list_table(_backup_rows(items)) if items else "no backups")


@backup.command("get", epilog="\b\nExamples:\n  capellactl bucket backup get nova-prod-01 BACKUP_ID")
@CLUSTER_ARG
@click.argument("backup_id", metavar="BACKUP_ID")
@PROJECT_OPT
@pass_state
def backup_get(state: AppState, cluster: str, backup_id: str, project: str | None) -> None:
    """Show one backup with its statistics."""
    client, pid, cl = _live(state, cluster, project)
    b = _get_backup(client, pid, str(cl["id"]), backup_id, cluster)
    if state.json:
        out(dumps(b))
        return
    out(_list_table(_backup_rows([b])))
    stats = b.get("stats") or {}
    out(f"  mutations {stats.get('mutations', 0):,} · tombstones {stats.get('tombstones', 0):,} · indexes "
        f"{stats.get('gsi', 0)} · search {stats.get('fts', 0)} · analytics {stats.get('cbas', 0)} · eventing "
        f"{stats.get('event', 0)} · took {b.get('elapsedTimeInSeconds', 0)} s · cycle {b.get('cycleID')}")


def _get_backup(client: Any, pid: str, cid: str, backup_id: str, cluster: str) -> dict[str, Any]:
    try:
        return ep.get_backup(client, pid, cid, backup_id)
    except NotFound:
        raise CliExit(ExitCode.ERROR, f"backup {backup_id} not found in cluster {cluster}",
                                      action=f"List them with 'capellactl bucket backup list {cluster}'.") from None


# ---------------------------------------------------------------------- create
@backup.command("create", epilog="\b\nExamples:\n  capellactl bucket backup create nova-prod-01 orders\n"
                                  "  capellactl --no-wait bucket backup create nova-prod-01 orders")
@CLUSTER_ARG
@click.argument("bucket")
@PROJECT_OPT
@pass_state
def backup_create(state: AppState, cluster: str, bucket: str, project: str | None) -> None:
    """Back a bucket up now and wait until the backup is ready."""
    client, pid, cl, bid = _live_bucket(state, cluster, bucket, project)
    cid = str(cl["id"])

    def latest() -> dict[str, Any] | None:  # Capella lists the latest backup of each bucket (not queued ones)
        return next((b for b in ep.list_cluster_backups(client, pid, cid) if b.get("bucketID") == bid
                     or b.get("bucketName") == bucket), None)

    before = (latest() or {}).get("id")
    note(f"→ backing up bucket {bucket} …")
    ep.create_bucket_backup(client, pid, cid, bid)
    if state.no_wait:
        out(f"backup of {bucket} started (--no-wait); see it with 'capellactl bucket backup list {cluster} {bucket}'")
        return
    found: dict[str, Any] = {}

    def status() -> str | None:
        b = latest()
        if b is None or b.get("id") == before:
            return None  # queued: not listed yet
        found.update(b)
        return str(b.get("status"))

    try:
        wait_for_status(status, DONE, FAILED, state.timeout, get_clock(), f"backup of {bucket}",
                        **progress(f"backup of {bucket}"))
    except StatusFailed as exc:
        raise CliExit(ExitCode.ERROR, f"Failed: {exc.what}", topic="backup",
                                      action=exc.action) from None
    except StatusTimeout as exc:
        raise CliExit(ExitCode.TIMEOUT, exc.what,
                                        action=exc.action) from None
    out(f"backup {found.get('id')} of {bucket} is ready")


# ---------------------------------------------------------------------- delete
@backup.command("delete", epilog="\b\nExamples:\n  capellactl bucket backup delete nova-prod-01 BACKUP_ID\n"
                                  "Deletes every backup of the backup's cycle (the weekly full and its incrementals).")
@CLUSTER_ARG
@click.argument("backup_id", metavar="BACKUP_ID")
@PROJECT_OPT
@pass_state
def backup_delete(state: AppState, cluster: str, backup_id: str, project: str | None) -> None:
    """Delete a backup and every other backup of its cycle."""
    client, pid, cl = _live(state, cluster, project)
    cid = str(cl["id"])
    try:
        b = ep.get_backup(client, pid, cid, backup_id)
    except NotFound:
        out(f"backup {backup_id} not found in cluster {cluster}, nothing to do")
        return
    bucket = str(b.get("bucketName"))
    try:
        in_cycle = ep.list_cycle_backups(client, pid, cid, str(b.get("bucketID")), str(b.get("cycleID")))
    except NotFound:
        in_cycle = [b]
    first = min((str(x.get("date")) for x in in_cycle), default=str(b.get("date")))
    out(f"  - deletes cycle {when(first)} with {len(in_cycle)} backup{'s' if len(in_cycle) != 1 else ''} of {bucket}")
    if not console.confirm_typed(state, "Type the bucket name to confirm deletion", "delete a backup cycle", bucket):
        out("Cancelled; nothing was deleted.")
        return
    with contextlib.suppress(NotFound):
        ep.delete_backup(client, pid, cid, backup_id)
    out(f"deleted the backup cycle of {bucket} that started {when(first)} ({len(in_cycle)} backups)")


# --------------------------------------------------------------------- restore
@backup.command("restore", epilog="\b\nExamples:\n"
                                   "  capellactl bucket backup restore nova-prod-01 BACKUP_ID --replace-ttl none\n"
                                   "  capellactl bucket backup restore nova-prod-01 BACKUP_ID --to-cluster nova-dr-01 "
                                   "--include-data orders.sales\n"
                                   "Without --force-updates, documents that are newer in the target are kept.")
@CLUSTER_ARG
@click.argument("backup_id", metavar="BACKUP_ID")
@click.option("--to-cluster", metavar="NAME", help="Restore into this cluster of the same project (default: the "
                                                  "backup's cluster).")
@click.option("--services", default="data", show_default=True, help="What to restore: data, query or data,query.")
@click.option("--include-data", metavar="B.S.C,…", help="Restore only these buckets, scopes or collections.")
@click.option("--exclude-data", metavar="B.S.C,…", help="Skip these buckets, scopes or collections.")
@click.option("--map-data", metavar="SRC=DST,…", help="Restore into other buckets, scopes or collections.")
@click.option("--filter-keys", metavar="REGEX", help="Only documents whose key matches.")
@click.option("--filter-values", metavar="REGEX", help="Only documents whose value matches.")
@click.option("--replace-ttl", type=click.Choice(["none", "all", "expired"]), help="Give documents a new expiry.")
@click.option("--replace-ttl-with", metavar="TIME", help="The new expiry (with --replace-ttl all or expired).")
@click.option("--force-updates", is_flag=True, help="Overwrite documents even when the target's are newer.")
@click.option("--auto-remove-collections", is_flag=True, help="Delete scopes and collections the backup knows were "
                                                              "deleted.")
@PROJECT_OPT
@pass_state
def backup_restore(state: AppState, cluster: str, backup_id: str, to_cluster: str | None, services: str,
                   include_data: str | None, exclude_data: str | None, map_data: str | None, filter_keys: str | None,
                   filter_values: str | None, replace_ttl: str | None, replace_ttl_with: str | None,
                   force_updates: bool, auto_remove_collections: bool, project: str | None) -> None:
    """Restore a bucket backup into the same or another cluster, all of it or part of it."""
    names = sorted({s.strip() for s in services.split(",") if s.strip()})
    if not names or set(names) - {"data", "query"}:
        raise CliExit(ExitCode.CONFIG_INVALID, f"--services takes data, query or data,query (got '{services}')",
                      topic="backup",
                                               action="Give data, query or data,query.")
    if replace_ttl_with and replace_ttl not in ("all", "expired"):
        raise CliExit(ExitCode.CONFIG_INVALID, "--replace-ttl-with was given without --replace-ttl",
                      topic="backup",
                                               action="Add --replace-ttl all or --replace-ttl expired.")
    client, pid, cl = _live(state, cluster, project)
    cid = str(cl["id"])
    b = _get_backup(client, pid, cid, backup_id, cluster)
    target = cl
    if to_cluster and to_cluster != cluster:
        target = find_cluster(client, pid, to_cluster)
        refuse_free(target)
    target_name = str(target.get("name"))
    if target.get("currentState") in ("turnedOff", "turningOff"):
        raise CliExit(ExitCode.BLOCKED, f"cluster {target_name} is turned off", topic="hibernation",
                                        action=f"Turn it on with 'capellactl cluster power {target_name} --on', then "
                                               f"run the command again.")
    body: dict[str, Any] = {"targetClusterID": str(target["id"]), "sourceClusterID": cid, "backupID": backup_id,
                            "services": names}
    for key, value in (("includeData", include_data), ("excludeData", exclude_data), ("mapData", map_data),
                       ("filterKeys", filter_keys), ("filterValues", filter_values), ("replaceTTL", replace_ttl),
                       ("replaceTTLWith", replace_ttl_with)):
        if value:
            body[key] = value
    if force_updates:
        body["forceUpdates"] = True
    if auto_remove_collections:
        body["autoRemoveCollections"] = True
    out(f"  ~ restore {b.get('bucketName')} from the backup of {when(b.get('date'))} UTC into {target_name}")
    out(f"    services: {', '.join(names)} · " + ("overwrites newer documents (--force-updates)" if force_updates else
                                                  f"newer documents in {target_name} are kept"))
    for label, value in (("only", include_data), ("skipping", exclude_data), ("mapped", map_data)):
        if value:
            out(f"    {label}: {value}")
    if not console.confirm_typed(state, "Type the target cluster name to confirm the restore", "restore a bucket",
                                 target_name):
        out("Cancelled; nothing was restored.")
        return
    ep.restore_backup(client, pid, cid, backup_id, body)
    out(f"restore of {b.get('bucketName')} into {target_name} started; Capella reports its progress in the "
        "cluster's activity log (the Management API has no restore status for bucket backups)")


# ---------------------------------------------------------------------- export
@backup.command("export", epilog="\b\nExamples:\n  capellactl bucket backup export nova-prod-01 BACKUP_ID\n"
                                  "  capellactl bucket backup export nova-prod-01 BACKUP_ID --export-id EXPORT_ID\n"
                                  "The download link is valid for one hour; run the command again for a new one.")
@CLUSTER_ARG
@click.argument("backup_id", metavar="BACKUP_ID")
@click.option("--export-id", metavar="ID", help="Show an export started earlier (its status and a new download link).")
@PROJECT_OPT
@pass_state
def backup_export(state: AppState, cluster: str, backup_id: str, export_id: str | None, project: str | None) -> None:
    """Package a backup cycle as a zip and print its download link."""
    client, pid, cl = _live(state, cluster, project)
    cid = str(cl["id"])
    b = _get_backup(client, pid, cid, backup_id, cluster)
    bid = str(b.get("bucketID"))
    if export_id is None:
        try:
            export_id = ep.export_backup(client, pid, cid, bid, backup_id)
        except Conflict:
            out(f"the backup cycle of {b.get('bucketName')} already has an export (Capella allows one per cycle); "
                f"show it with --export-id ID (printed when it was started)")
            return
        except ValidationFailed as exc:
            raise CliExit(ExitCode.BLOCKED, f"Capella cannot export this backup: {exc.message}", topic="backup",
                                            action="Choose another backup ('capellactl bucket backup list "
                                                   "CLUSTER'), or take a new one with 'capellactl bucket backup "
                                                   "create'.") \
                from None
        out(f"export {export_id} of {b.get('bucketName')} started")
    found: dict[str, Any] = {}

    def status() -> str | None:
        found.clear()
        found.update(ep.get_backup_export(client, pid, cid, bid, backup_id, str(export_id)))
        return str(found.get("status"))

    if state.no_wait:
        status()
    else:
        try:
            wait_for_status(status, {"complete"}, {"failed", "expired"}, state.timeout, get_clock(),
                            f"export {export_id}", **progress(f"export of {b.get('bucketName')}"))
        except StatusFailed as exc:
            raise CliExit(ExitCode.ERROR, f"Failed: {exc.what}", topic="backup",
                                          action=exc.action) from None
        except StatusTimeout as exc:
            raise CliExit(ExitCode.TIMEOUT, exc.what,
                                            action=exc.action) from None
    if state.json:
        out(dumps(found))
        return
    if found.get("status") != "complete":
        out(f"export {export_id}: {found.get('status')}; run this command with --export-id {export_id} to check again")
        return
    out(f"export {export_id} is complete: {found.get('sizeInBytes', 0) / 1024 ** 3:.1f} GB, available until "
        f"{when(found.get('expiration'))} UTC")
    out("download (valid for one hour; treat it like a password):")
    out(f"  {found.get('backupDownloadURL')}")
