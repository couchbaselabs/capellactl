"""bucket list | get | create | update | delete (CAP-023, CAP-024).

create and update record the bucket in capella.yaml and apply it, like the cluster commands (CAP-038);
delete removes it from Capella and from the file, after a typed confirmation.
"""

from __future__ import annotations

from typing import Any

import click
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from capellactl.api import endpoints as ep
from capellactl.cli import console
from capellactl.cli.cluster_ops import _ask, change_and_apply, locate, open_editor
from capellactl.cli.console import note, out
from capellactl.cli.env import pass_state
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.groups import SuggestingGroup
from capellactl.cli.resource_cmds import _table, complete_cluster_names, file_projects, live_cluster
from capellactl.cli.state import AppState
from capellactl.config.editor import put, to_commented
from capellactl.output.render import dumps
from capellactl.resources.bucket import delete_details
from capellactl.resources.cluster import is_free
from capellactl.resources.guards import deletion_protected, protection_message

TYPES = ["couchbase", "ephemeral"]
BACKENDS = ["couchstore", "magma"]
DURABILITY = ["none", "majority", "majorityAndPersistActive", "persistToMajority"]
CONFLICT = ["seqno", "lww"]
EVICTION = ["fullEviction", "noEviction", "nruEviction"]
PROJECT_OPT = click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name repeats).")
GET_FIELDS = ("id", "name", "type", "storageBackend", "vbuckets", "memoryAllocationInMb", "bucketConflictResolution",
              "durabilityLevel", "replicas", "flushEnabled", "timeToLiveInSeconds", "evictionPolicy", "priority",
              "enableCrossClusterVersioning")


@click.group(cls=SuggestingGroup, epilog="\b\nExamples:\n  capellactl bucket list nova-dev-01\n"
                                         "  capellactl bucket create nova-dev-01 orders --memory 1024 "
                                         "--storage-backend magma\n"
                                         "  capellactl bucket update nova-dev-01 orders --memory 2048\n"
                                         "  capellactl bucket get nova-dev-01 orders\n"
                                         "  capellactl bucket delete nova-dev-01 orders")
def bucket() -> None:
    """Buckets: list, get, create, update, delete."""


def _file_buckets(state: AppState, cluster: str, project: str | None) -> set[str]:
    names: set[str] = set()
    for p in file_projects(state):
        if project and p.get("name") != project:
            continue
        for c in p.get("clusters") or []:
            if isinstance(c, dict) and c.get("name") == cluster:
                names.update(str(b.get("name")) for b in c.get("buckets") or [] if isinstance(b, dict))
    return names


def _buckets(client: Any, pid: str, cl: dict[str, Any]) -> list[dict[str, Any]]:
    """Buckets of a cluster; free-tier clusters have their own endpoint."""
    cid = str(cl["id"])
    return ep.list_free_buckets(client, pid, cid)[0] if is_free(cl) else ep.list_buckets(client, pid, cid)


def _get_bucket(client: Any, pid: str, cl: dict[str, Any], bucket_id: str) -> dict[str, Any]:
    getter = ep.get_free_bucket if is_free(cl) else ep.get_bucket
    return getter(client, pid, str(cl["id"]), bucket_id)[0]


def _find_bucket(client: Any, pid: str, cl: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((b for b in _buckets(client, pid, cl) if b.get("name") == name), None)


# --------------------------------------------------------------------- read
@bucket.command("list")
@click.argument("cluster", shell_complete=complete_cluster_names)
@PROJECT_OPT
@pass_state
def bucket_list(state: AppState, cluster: str, project: str | None) -> None:
    """List the buckets of a cluster."""
    client, pid, cl = live_cluster(state, cluster, project)
    items = _buckets(client, pid, cl)
    if state.json:
        out(dumps(items))
        return
    declared = _file_buckets(state, cluster, project)
    rows: list[tuple[str, ...]] = [("NAME", "TYPE", "STORAGE", "MEMORY MB", "REPLICAS", "DURABILITY", "TTL", "ITEMS",
                                    "IN FILE")]
    for b in items:
        rows.append((str(b.get("name")), str(b.get("type", "")), str(b.get("storageBackend") or "-"),
                     str(b.get("memoryAllocationInMb", "")), str(b.get("replicas", "")),
                     str(b.get("durabilityLevel", "")), str(b.get("timeToLiveInSeconds", "")),
                     f"{int((b.get('stats') or {}).get('itemCount') or 0):,}",
                     "yes" if b.get("name") in declared else "-"))
    out(_table(rows))


@bucket.command("get")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("name")
@PROJECT_OPT
@pass_state
def bucket_get(state: AppState, cluster: str, name: str, project: str | None) -> None:
    """Show one bucket: settings and usage."""
    client, pid, cl = live_cluster(state, cluster, project)
    found = _find_bucket(client, pid, cl, name)
    if found is None:
        raise CliExit(ExitCode.ERROR, f"bucket {cluster}/{name} not found")
    body = _get_bucket(client, pid, cl, str(found["id"]))
    if state.json:
        out(dumps(body))
        return
    rows = [("FIELD", "VALUE")] + [(k, str(body[k]).lower() if isinstance(body[k], bool) else str(body[k]))
                                   for k in GET_FIELDS if k in body]
    out(_table(rows))
    stats = body.get("stats") or {}
    if stats:
        out(f"items: {int(stats.get('itemCount') or 0):,}   memory used: {stats.get('memoryUsedInMib', '-')} MB   "
            f"disk used: {stats.get('diskUsedInMib', '-')} MB")


# ------------------------------------------------------------ create/update
def _refuse_on_free_tier(proj: Any, cl: CommentedMap, cluster: str, flags: dict[str, Any], allowed: str,
                         retry: str) -> None:
    """Name the flags a free-tier cluster cannot take, before anything is written (CAP-023 AC5)."""
    given = [f for f, v in flags.items() if v is not None]
    if cl.get("tier") != "free" or not given:
        return
    raise CliExit(ExitCode.CONFIG_INVALID,
                  f"{cluster} (project {proj.get('name')}) is a free-tier cluster: Capella chooses its bucket settings, "
                  f"so {', '.join(given)} cannot be set. Only {allowed} can be set.\nTry: {retry}\n"
                  "For the other settings, use a provisioned cluster (capellactl cluster list shows the PLAN column).")


def _bucket_in_capella(state: AppState, cluster: str, project: str | None, name: str) -> bool:
    """True when the bucket exists in Capella; False when it, or its cluster, has not been created yet."""
    try:
        client, pid, cl = live_cluster(state, cluster, project)
    except CliExit:
        return False
    return _find_bucket(client, pid, cl, name) is not None


def _bucket_node(cl: CommentedMap, name: str) -> CommentedMap | None:
    return next((b for b in cl.get("buckets") or [] if isinstance(b, CommentedMap) and b.get("name") == name), None)


@bucket.command("create", epilog="\b\nExamples:\n  capellactl bucket create nova-dev-01 orders --memory 1024 "
                                  "--storage-backend magma --durability majority\n"
                                  "  capellactl bucket create nova-dev-01 sessions --type ephemeral --memory 256 "
                                  "--eviction-policy nruEviction\n"
                                  "  capellactl bucket create nova-dev-01 orders --no-apply")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("name")
@click.option("--memory", type=click.IntRange(min=1), help="memoryAllocationInMb (asked; default 1024).")
@click.option("--type", "type_", type=click.Choice(TYPES), help="Bucket type (default couchbase). Cannot change later.")
@click.option("--storage-backend", type=click.Choice(BACKENDS), help="couchbase buckets only. Cannot change later.")
@click.option("--vbuckets", type=click.Choice(["128", "1024"]), help="magma on server 8.0+. Cannot change later.")
@click.option("--replicas", type=click.IntRange(0, 3), help="Replicas (default 1; 0 on single-node clusters).")
@click.option("--durability", type=click.Choice(DURABILITY), help="durabilityLevel (default none).")
@click.option("--ttl", type=click.IntRange(min=0), help="timeToLiveInSeconds (default 0: no bucket TTL).")
@click.option("--flush/--no-flush", "flush", default=None, help="flushEnabled (default off).")
@click.option("--conflict-resolution", type=click.Choice(CONFLICT), help="seqno or lww (default seqno). Cannot "
              "change later.")
@click.option("--eviction-policy", type=click.Choice(EVICTION), help="Cannot change later.")
@click.option("--priority", type=click.IntRange(min=0), help="Recovery priority (server 7.6+).")
@PROJECT_OPT
@click.option("--no-apply", is_flag=True, help="Only add the bucket to capella.yaml; create it later with apply.")
@pass_state
def bucket_create(state: AppState, cluster: str, name: str, memory: int | None, type_: str | None,
                  storage_backend: str | None, vbuckets: str | None, replicas: int | None, durability: str | None,
                  ttl: int | None, flush: bool | None, conflict_resolution: str | None, eviction_policy: str | None,
                  priority: int | None, project: str | None, no_apply: bool) -> None:
    """Create a bucket: records it in capella.yaml and creates it in Capella (an existing one is adopted)."""
    ed = open_editor(state)
    proj, cl = locate(ed, cluster, project)
    _refuse_on_free_tier(proj, cl, cluster, {
        "--type": type_, "--storage-backend": storage_backend, "--vbuckets": vbuckets, "--replicas": replicas,
        "--durability": durability, "--ttl": ttl, "--flush/--no-flush": flush,
        "--conflict-resolution": conflict_resolution, "--eviction-policy": eviction_policy, "--priority": priority,
    }, "--memory", f"capellactl bucket create {cluster} {name}" + (f" --memory {memory}" if memory else " --memory MB"))
    recorded = _bucket_node(cl, name)
    if recorded is not None and _bucket_in_capella(state, cluster, project, name):
        raise CliExit(ExitCode.BLOCKED, f"bucket {name} is already in capella.yaml for {cluster}; change it with "
                                        f"'capellactl bucket update {cluster} {name}'", topic="idempotency")
    if recorded is not None:  # recorded by an earlier run that did not finish: complete it instead of refusing
        out(f"bucket {name} is in capella.yaml but not in Capella yet (an earlier run did not finish); creating it now")
    if memory is None and recorded is None and console.is_interactive():
        memory = _ask("Memory (MB)", 1024, kind=int)
    fields: dict[str, Any] = {"name": name, "type": type_, "storageBackend": storage_backend,
                              "vbuckets": int(vbuckets) if vbuckets else None, "memoryAllocationInMb": memory,
                              "bucketConflictResolution": conflict_resolution, "durabilityLevel": durability,
                              "replicas": replicas, "flushEnabled": flush, "timeToLiveInSeconds": ttl,
                              "evictionPolicy": eviction_policy, "priority": priority}
    if recorded is not None:
        for k, v in fields.items():
            if v is not None:
                recorded[k] = v
    else:
        if "buckets" not in cl or not isinstance(cl.get("buckets"), CommentedSeq):
            put(cl, "buckets", CommentedSeq())
        cl["buckets"].append(to_commented({k: v for k, v in fields.items() if v is not None}))
    change_and_apply(state, ed, f"bucket/{cluster}/{name}",
                     f"Add bucket {name} to capella.yaml and create it in {cluster}?", no_apply,
                     noop_message=f"bucket {cluster}/{name} already exists in Capella with these settings; "
                                  "recorded it in capella.yaml")


@bucket.command("update", epilog="\b\nExamples:\n  capellactl bucket update nova-dev-01 orders --memory 2048\n"
                                  "  capellactl bucket update nova-dev-01 orders --replicas 2 --durability majority\n"
                                  "  capellactl bucket update nova-dev-01 orders            (asks what to change)")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("name")
@click.option("--memory", type=click.IntRange(min=1), help="memoryAllocationInMb.")
@click.option("--replicas", type=click.IntRange(0, 3), help="Replicas (takes full effect after a rebalance; single-node clusters: 0).")
@click.option("--durability", type=click.Choice(DURABILITY), help="durabilityLevel.")
@click.option("--ttl", type=click.IntRange(min=0), help="timeToLiveInSeconds.")
@click.option("--flush/--no-flush", "flush", default=None, help="flushEnabled.")
@click.option("--priority", type=click.IntRange(min=0), help="Recovery priority (server 7.6+).")
@click.option("--cross-cluster-versioning/--no-cross-cluster-versioning", "versioning", default=None,
              help="enableCrossClusterVersioning.")
@PROJECT_OPT
@click.option("--no-apply", is_flag=True, help="Only update capella.yaml; apply later.")
@pass_state
def bucket_update(state: AppState, cluster: str, name: str, memory: int | None, replicas: int | None,
                  durability: str | None, ttl: int | None, flush: bool | None, priority: int | None,
                  versioning: bool | None, project: str | None, no_apply: bool) -> None:
    """Change a bucket's memory, replicas, durability, TTL, flush or priority; records it in capella.yaml and applies.

    type, storageBackend, vbuckets, bucketConflictResolution and evictionPolicy cannot be changed.
    """
    ed = open_editor(state)
    proj, cl = locate(ed, cluster, project)
    free = cl.get("tier") == "free"
    _refuse_on_free_tier(proj, cl, cluster, {
        "--replicas": replicas, "--durability": durability, "--ttl": ttl, "--flush/--no-flush": flush,
        "--priority": priority,
    }, "--memory and --cross-cluster-versioning", f"capellactl bucket update {cluster} {name} --memory MB")
    node = _bucket_node(cl, name)
    if node is None:
        raise CliExit(ExitCode.CONFIG_INVALID, f"bucket {name} is not in capella.yaml for {cluster}; add it with "
                                               f"'capellactl bucket create {cluster} {name}' (an existing bucket is "
                                               "adopted, not re-created)")
    values = {"memoryAllocationInMb": memory, "replicas": replicas, "durabilityLevel": durability,
              "timeToLiveInSeconds": ttl, "flushEnabled": flush, "priority": priority,
              "enableCrossClusterVersioning": versioning}
    if all(v is None for v in values.values()):
        if not console.is_interactive():
            raise CliExit(ExitCode.CONFIG_INVALID, "nothing to change; pass for example --memory, --replicas, "
                                                   "--durability or --ttl")
        out(f"Press Enter to keep the current value of {name}.")
        values["memoryAllocationInMb"] = _ask("Memory (MB)", node.get("memoryAllocationInMb", 1024), kind=int)
        if not free:  # Capella chooses the rest on the free tier
            values["replicas"] = _ask("Replicas", node.get("replicas", 1), kind=click.IntRange(0, 3))
            values["durabilityLevel"] = _ask("Durability", node.get("durabilityLevel", "none"), DURABILITY)
            values["timeToLiveInSeconds"] = _ask("TTL seconds (0: none)", node.get("timeToLiveInSeconds", 0),
                                                 kind=int)
    for k, v in values.items():
        if v is not None:
            node[k] = v
    change_and_apply(state, ed, f"bucket/{cluster}/{name}",
                     f"Record these changes in capella.yaml and apply them to bucket {name}?", no_apply)


# ------------------------------------------------------------------- delete
@bucket.command("delete", epilog="\b\nExamples:\n  capellactl bucket delete nova-dev-01 orders\n"
                                  "  capellactl --auto-approve bucket delete nova-dev-01 orders")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("name")
@PROJECT_OPT
@pass_state
def bucket_delete(state: AppState, cluster: str, name: str, project: str | None) -> None:
    """Delete a bucket and all its data from Capella, and remove it from capella.yaml (CAP-024)."""
    client, pid, cl = live_cluster(state, cluster, project)
    cid = str(cl["id"])
    found = _find_bucket(client, pid, cl, name)
    if found is None:
        out(f"bucket {cluster}/{name} not found, nothing to do")
        _remove_from_file(state, cluster, name, project)
        return
    if deletion_protected(cl):
        raise CliExit(ExitCode.BLOCKED, protection_message(cluster), topic="safety")
    body = _get_bucket(client, pid, cl, str(found["id"]))
    out(f"  - bucket {cluster}/{name}")
    for line in delete_details(client, pid, cid, body):
        out(f"  {line}")
    if not console.confirm_typed(state, "Type the bucket name to confirm deletion", "delete a bucket", name):
        out("Cancelled; nothing was deleted.")
        return
    delete = ep.delete_free_bucket if is_free(cl) else ep.delete_bucket
    delete(client, pid, cid, str(found["id"]))  # the id always comes from the list response
    out(f"deleted bucket {cluster}/{name}")
    _remove_from_file(state, cluster, name, project)


def _remove_from_file(state: AppState, cluster: str, name: str, project: str | None) -> None:
    """Keep capella.yaml in step, so the next apply does not create the bucket again."""
    from capellactl.config.editor import ConfigEditor

    path = state.config_path()
    if not path.exists() or name not in _file_buckets(state, cluster, project):
        return
    ed = ConfigEditor(path)
    try:
        found = ed.find_cluster(cluster, project)
    except LookupError:
        return
    if found is None:
        return
    seq = found[1].get("buckets") or []
    for i, b in enumerate(seq):
        if isinstance(b, CommentedMap) and b.get("name") == name:
            del seq[i]
            break
    if not seq:
        del found[1]["buckets"]
    backup = ed.save()
    note(f"removed bucket {name} from {path.name} (previous version kept as {backup.name})")
