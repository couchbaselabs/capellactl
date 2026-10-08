"""scope list | create | delete and collection list | create | update | delete (CAP-025, CAP-026).

create and update record the scope or collection in capella.yaml and apply it, like the bucket commands;
delete removes it from Capella and from the file, after a typed confirmation. The _default and _system
scopes and the _default collection are system objects and are never created, changed or deleted.
"""

from __future__ import annotations

from typing import Any

import click
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from capellactl.api import endpoints as ep
from capellactl.cli import console
from capellactl.cli.bucket_cmds import PROJECT_OPT, _bucket_node, _find_bucket
from capellactl.cli.cluster_ops import _ask, change_and_apply, locate, open_editor
from capellactl.cli.console import err, out
from capellactl.cli.env import pass_state
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.groups import SuggestingGroup
from capellactl.cli.resource_cmds import _table, complete_cluster_names, file_projects, live_cluster
from capellactl.cli.state import AppState
from capellactl.config.editor import to_commented
from capellactl.output.render import dumps
from capellactl.resources.guards import deletion_protected, protection_message
from capellactl.resources.scope import (
    DEFAULT,
    SYSTEM_DELETE_MESSAGE,
    delete_details,
    is_system_collection,
    is_system_scope,
)

MAX_TTL_HELP = "maxTTL in seconds: -1 never expire, 0 use the bucket's TTL, >0 seconds."
NO_APPLY_OPT = click.option("--no-apply", is_flag=True, help="Only update capella.yaml; apply later.")


@click.group(cls=SuggestingGroup, epilog="\b\nExamples:\n  capellactl scope list nova-dev-01 orders\n"
                                         "  capellactl scope create nova-dev-01 orders billing\n"
                                         "  capellactl scope delete nova-dev-01 orders billing")
def scope() -> None:
    """Scopes: list, create, delete."""


@click.group(cls=SuggestingGroup, epilog="\b\nExamples:\n  capellactl collection list nova-dev-01 orders inventory\n"
                                         "  capellactl collection create nova-dev-01 orders inventory items\n"
                                         "  capellactl collection update nova-dev-01 orders inventory items "
                                         "--max-ttl 3600\n"
                                         "  capellactl collection delete nova-dev-01 orders inventory items")
def collection() -> None:
    """Collections: list, create, update, delete."""


# ------------------------------------------------------------------ helpers
def _declared(state: AppState, cluster: str, bucket: str, project: str | None) -> dict[str, set[str]]:
    """Scope name → collection names declared in capella.yaml for one bucket."""
    found: dict[str, set[str]] = {}
    for p in file_projects(state):
        if project and p.get("name") != project:
            continue
        for c in p.get("clusters") or []:
            if not isinstance(c, dict) or c.get("name") != cluster:
                continue
            for b in c.get("buckets") or []:
                if isinstance(b, dict) and b.get("name") == bucket:
                    for s in b.get("scopes") or []:
                        if isinstance(s, dict):
                            found.setdefault(str(s.get("name")), set()).update(
                                str(x.get("name")) for x in s.get("collections") or [] if isinstance(x, dict))
    return found


def _live_bucket(state: AppState, cluster: str, bucket: str,
                 project: str | None) -> tuple[Any, str, dict[str, Any], dict[str, Any] | None]:
    client, pid, cl = live_cluster(state, cluster, project)
    return client, pid, cl, _find_bucket(client, pid, cl, bucket)


def _require_bucket(found: dict[str, Any] | None, cluster: str, bucket: str) -> dict[str, Any]:
    if found is None:
        raise CliExit(ExitCode.ERROR, f"bucket {cluster}/{bucket} not found")
    return found


def _in_file(declared: bool, system: bool) -> str:
    return "yes" if declared else ("system" if system else "-")


def _bucket_in_file(ed: Any, cluster: str, bucket: str, project: str | None) -> CommentedMap:
    _, cl = locate(ed, cluster, project)
    node = _bucket_node(cl, bucket)
    if node is None:
        raise CliExit(ExitCode.CONFIG_INVALID, f"bucket {bucket} is not in capella.yaml for {cluster}; add it with "
                                               f"'capellactl bucket create {cluster} {bucket}' (an existing bucket "
                                               "is adopted, not re-created)")
    return node


def _child(node: CommentedMap, key: str, name: str) -> CommentedMap | None:
    return next((x for x in node.get(key) or [] if isinstance(x, CommentedMap) and x.get("name") == name), None)


def _append(node: CommentedMap, key: str, item: dict[str, Any]) -> CommentedMap:
    if key not in node or not isinstance(node.get(key), CommentedSeq):
        node[key] = CommentedSeq()
    entry = to_commented(item)
    node[key].append(entry)
    return entry  # type: ignore[no-any-return]


def _confirm_typed(state: AppState, kind: str, name: str) -> bool:
    if state.auto_approve:
        return True
    if not console.is_interactive():
        raise CliExit(ExitCode.ERROR, "refusing to delete without --auto-approve in a non-interactive session")
    typed = click.prompt(f"Type the {kind} name to confirm deletion", default="", show_default=False)
    if typed.strip() != name:
        out("Cancelled; nothing was deleted.")
        return False
    return True


def _remove_from_file(state: AppState, cluster: str, bucket: str, scope_name: str, coll: str | None,
                      project: str | None) -> None:
    """Keep capella.yaml in step, so the next apply does not create the scope or collection again."""
    from capellactl.config.editor import ConfigEditor

    declared = _declared(state, cluster, bucket, project)
    if scope_name not in declared or (coll is not None and coll not in declared[scope_name]):
        return
    ed = ConfigEditor(state.config_path())
    try:
        found = ed.find_cluster(cluster, project)
    except LookupError:
        return
    b = _bucket_node(found[1], bucket) if found else None
    s = _child(b, "scopes", scope_name) if b is not None else None
    if b is None or s is None:
        return
    if coll is None:
        b["scopes"].remove(s)
        what = f"scope {scope_name}"
    else:
        s["collections"].remove(_child(s, "collections", coll))
        if not s["collections"]:
            del s["collections"]
        what = f"collection {scope_name}.{coll}"
    if not b["scopes"]:
        del b["scopes"]
    backup = ed.save()
    err(f"removed {what} from {ed.path.name} (previous version kept as {backup.name})")


# -------------------------------------------------------------------- scope
@scope.command("list")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("bucket")
@PROJECT_OPT
@pass_state
def scope_list(state: AppState, cluster: str, bucket: str, project: str | None) -> None:
    """List the scopes of a bucket."""
    client, pid, cl, found = _live_bucket(state, cluster, bucket, project)
    b = _require_bucket(found, cluster, bucket)
    items = ep.list_scopes(client, pid, str(cl["id"]), str(b["id"]))
    if state.json:
        out(dumps(items))
        return
    declared = _declared(state, cluster, bucket, project)
    rows: list[tuple[str, ...]] = [("NAME", "COLLECTIONS", "IN FILE")]
    for s in items:
        name = str(s.get("name"))
        colls = [c for c in s.get("collections") or [] if not is_system_collection(name, c.get("name"))]
        rows.append((name, str(len(colls)), _in_file(name in declared, is_system_scope(name))))
    out(_table(rows))


@scope.command("create", epilog="\b\nExamples:\n  capellactl scope create nova-dev-01 orders billing\n"
                                 "  capellactl scope create nova-dev-01 orders billing --no-apply")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("bucket")
@click.argument("name")
@PROJECT_OPT
@NO_APPLY_OPT
@pass_state
def scope_create(state: AppState, cluster: str, bucket: str, name: str, project: str | None, no_apply: bool) -> None:
    """Create a scope: records it in capella.yaml and creates it in Capella (an existing one is adopted)."""
    if is_system_scope(name):
        raise CliExit(ExitCode.CONFIG_INVALID, f"{name} is a system scope that every bucket has; add collections to "
                                               f"_default with 'capellactl collection create {cluster} {bucket} "
                                               f"{DEFAULT} NAME'" if name == DEFAULT else
                      f"{name} is a system scope and cannot be created")
    ed = open_editor(state)
    b = _bucket_in_file(ed, cluster, bucket, project)
    added = _child(b, "scopes", name) is None
    if added:
        _append(b, "scopes", {"name": name})
    change_and_apply(state, ed, f"scope/{cluster}/{bucket}/{name}",
                     f"{'Add' if added else 'Keep'} scope {name} in capella.yaml and create it in {cluster}/{bucket}?",
                     no_apply, noop_message=f"scope {cluster}/{bucket}/{name} already exists in Capella"
                                            + ("; recorded it in capella.yaml" if added else ""))


@scope.command("delete", epilog="\b\nExamples:\n  capellactl scope delete nova-dev-01 orders billing\n"
                                 "  capellactl --auto-approve scope delete nova-dev-01 orders billing")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("bucket")
@click.argument("name")
@PROJECT_OPT
@pass_state
def scope_delete(state: AppState, cluster: str, bucket: str, name: str, project: str | None) -> None:
    """Delete a scope, its collections and all their documents, and remove it from capella.yaml (CAP-026)."""
    if is_system_scope(name):
        raise CliExit(ExitCode.BLOCKED, SYSTEM_DELETE_MESSAGE, topic="safety")
    key = f"{cluster}/{bucket}/{name}"
    client, pid, cl, found = _live_bucket(state, cluster, bucket, project)
    cid = str(cl["id"])
    if found is None or name not in {s.get("name") for s in ep.list_scopes(client, pid, cid, str(found["id"]))}:
        out(f"scope {key} not found, nothing to do")
        _remove_from_file(state, cluster, bucket, name, None, project)
        return
    if deletion_protected(cl):
        raise CliExit(ExitCode.BLOCKED, protection_message(cluster), topic="safety")
    out(f"  - scope {key}")
    for line in delete_details(client, pid, cid, bucket, str(found["id"]), name):
        out(f"  {line}")
    if not _confirm_typed(state, "scope", name):
        return
    ep.delete_scope(client, pid, cid, str(found["id"]), name)
    out(f"deleted scope {key}")
    _remove_from_file(state, cluster, bucket, name, None, project)


# --------------------------------------------------------------- collection
@collection.command("list")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("bucket")
@click.argument("scope_name", metavar="SCOPE")
@PROJECT_OPT
@pass_state
def collection_list(state: AppState, cluster: str, bucket: str, scope_name: str, project: str | None) -> None:
    """List the collections of a scope."""
    client, pid, cl, found = _live_bucket(state, cluster, bucket, project)
    b = _require_bucket(found, cluster, bucket)
    items = ep.list_collections(client, pid, str(cl["id"]), str(b["id"]), scope_name)
    if state.json:
        out(dumps(items))
        return
    declared = _declared(state, cluster, bucket, project).get(scope_name, set())
    rows: list[tuple[str, ...]] = [("NAME", "MAX TTL", "IN FILE")]
    for c in items:
        name = str(c.get("name"))
        rows.append((name, str(c.get("maxTTL", "")),
                     _in_file(name in declared, is_system_collection(scope_name, name))))
    out(_table(rows))


def _coll_args(f: Any) -> Any:
    for dec in reversed((click.argument("cluster", shell_complete=complete_cluster_names), click.argument("bucket"),
                         click.argument("scope_name", metavar="SCOPE"), click.argument("name"))):
        f = dec(f)
    return f


@collection.command("create", epilog="\b\nExamples:\n  capellactl collection create nova-dev-01 orders inventory items\n"
                                      "  capellactl collection create nova-dev-01 orders inventory suppliers "
                                      "--max-ttl -1\n"
                                      "  capellactl collection create nova-dev-01 orders _default legacy")
@_coll_args
@click.option("--max-ttl", type=click.IntRange(min=-1), help=MAX_TTL_HELP + " Default: Capella's (0).")
@PROJECT_OPT
@NO_APPLY_OPT
@pass_state
def collection_create(state: AppState, cluster: str, bucket: str, scope_name: str, name: str, max_ttl: int | None,
                      project: str | None, no_apply: bool) -> None:
    """Create a collection: records it (and its scope) in capella.yaml and creates it in Capella.

    An existing collection is adopted. A scope that is not in capella.yaml yet is added too.
    """
    if is_system_collection(scope_name, name) or scope_name == "_system":
        raise CliExit(ExitCode.CONFIG_INVALID, f"{scope_name}.{name} is a system collection and cannot be created")
    ed = open_editor(state)
    b = _bucket_in_file(ed, cluster, bucket, project)
    s = _child(b, "scopes", scope_name) or _append(b, "scopes", {"name": scope_name})
    if _child(s, "collections", name) is not None:
        raise CliExit(ExitCode.BLOCKED, f"collection {scope_name}.{name} is already in capella.yaml for "
                                        f"{cluster}/{bucket}; change it with 'capellactl collection update {cluster} "
                                        f"{bucket} {scope_name} {name}'", topic="idempotency")
    _append(s, "collections", {"name": name, **({"maxTTL": max_ttl} if max_ttl is not None else {})})
    change_and_apply(state, ed, f"collection/{cluster}/{bucket}/{scope_name}/{name}",
                     f"Add collection {scope_name}.{name} to capella.yaml and create it in {cluster}/{bucket}?",
                     no_apply, noop_message=f"collection {cluster}/{bucket}/{scope_name}/{name} already exists in "
                                            "Capella with these settings; recorded it in capella.yaml")


@collection.command("update", epilog="\b\nExamples:\n  capellactl collection update nova-dev-01 orders inventory items "
                                      "--max-ttl 3600\n"
                                      "  capellactl collection update nova-dev-01 orders inventory items --max-ttl -1")
@_coll_args
@click.option("--max-ttl", type=click.IntRange(min=-1), help=MAX_TTL_HELP + " Needs Couchbase Server 7.6.0 or later.")
@PROJECT_OPT
@NO_APPLY_OPT
@pass_state
def collection_update(state: AppState, cluster: str, bucket: str, scope_name: str, name: str, max_ttl: int | None,
                      project: str | None, no_apply: bool) -> None:
    """Change a collection's maxTTL; records it in capella.yaml and applies it (Couchbase Server 7.6.0 or later)."""
    ed = open_editor(state)
    b = _bucket_in_file(ed, cluster, bucket, project)
    s = _child(b, "scopes", scope_name)
    node = _child(s, "collections", name) if s is not None else None
    if node is None:
        raise CliExit(ExitCode.CONFIG_INVALID, f"collection {scope_name}.{name} is not in capella.yaml for "
                                               f"{cluster}/{bucket}; add it with 'capellactl collection create "
                                               f"{cluster} {bucket} {scope_name} {name}' (an existing collection is "
                                               "adopted, not re-created)")
    if max_ttl is None:
        if not console.is_interactive():
            raise CliExit(ExitCode.CONFIG_INVALID, "nothing to change; pass --max-ttl SECONDS")
        max_ttl = _ask("maxTTL seconds (-1 never expire, 0 bucket TTL)", node.get("maxTTL", 0),
                       kind=click.IntRange(min=-1))
    node["maxTTL"] = max_ttl
    change_and_apply(state, ed, f"collection/{cluster}/{bucket}/{scope_name}/{name}",
                     f"Record this change in capella.yaml and apply it to collection {scope_name}.{name}?", no_apply)


@collection.command("delete", epilog="\b\nExamples:\n  capellactl collection delete nova-dev-01 orders billing invoices\n"
                                      "  capellactl --auto-approve collection delete nova-dev-01 orders billing "
                                      "invoices")
@_coll_args
@PROJECT_OPT
@pass_state
def collection_delete(state: AppState, cluster: str, bucket: str, scope_name: str, name: str,
                      project: str | None) -> None:
    """Delete a collection and all its documents, and remove it from capella.yaml (CAP-026)."""
    if is_system_collection(scope_name, name):
        raise CliExit(ExitCode.BLOCKED, SYSTEM_DELETE_MESSAGE, topic="safety")
    key = f"{cluster}/{bucket}/{scope_name}/{name}"
    client, pid, cl, found = _live_bucket(state, cluster, bucket, project)
    cid = str(cl["id"])
    names: set[Any] = set()
    if found is not None:
        scopes = {s.get("name"): s for s in ep.list_scopes(client, pid, cid, str(found["id"]))}
        names = {c.get("name") for c in (scopes.get(scope_name) or {}).get("collections") or []}
    if name not in names:
        out(f"collection {key} not found, nothing to do")
        _remove_from_file(state, cluster, bucket, scope_name, name, project)
        return
    assert found is not None
    if deletion_protected(cl):
        raise CliExit(ExitCode.BLOCKED, protection_message(cluster), topic="safety")
    out(f"  - collection {key}")
    for line in delete_details(client, pid, cid, bucket, str(found["id"]), scope_name, name):
        out(f"  {line}")
    if not _confirm_typed(state, "collection", name):
        return
    ep.delete_collection(client, pid, cid, str(found["id"]), scope_name, name)
    out(f"deleted collection {key}")
    _remove_from_file(state, cluster, bucket, scope_name, name, project)
