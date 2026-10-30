"""Per-resource command groups: list, get, create, update, delete (00-architecture.md section 5).

create/update record the change in capella.yaml and apply that one resource; the top-level `apply`
reconciles the whole file. `project apply` and `cluster apply` remain as hidden aliases.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import click
from click.shell_completion import CompletionItem

from capellactl.api import endpoints as ep
from capellactl.cli.console import out
from capellactl.cli.env import pass_state, run_apply
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.groups import SuggestingGroup
from capellactl.cli.state import AppState
from capellactl.output.render import dumps


def _table(rows: Sequence[tuple[str, ...]]) -> str:
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in rows)


def _list_table(rows: Sequence[tuple[str, ...]]) -> str:
    """A list command's table: rows numbered 1, 2, 3 … in an S.NO column."""
    return _table([("S.NO", *rows[0])] + [(str(n), *r) for n, r in enumerate(rows[1:], 1)])


def complete_cluster_names(ctx: click.Context, param: click.Parameter, incomplete: str) -> list[CompletionItem]:
    """Cluster names from the config file in the current directory; no API call (CAP-034 AC6)."""
    import yaml

    for name in ("capella.yaml", "capella.yml"):
        p = Path(name)
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                return []
            from capellactl.config.loader import project_entries

            names = sorted({str(c.get("name")) for e in project_entries(data) for c in e.clusters if isinstance(c, dict)})
            return [CompletionItem(n) for n in names if n.startswith(incomplete)]
    return []


def file_projects(state: AppState) -> list[dict[str, Any]]:
    """Projects declared in capella.yaml, each with its clusters, read without resolving secrets (empty when there
    is no file)."""
    import yaml

    from capellactl.config.loader import project_entries

    path = state.config_path()
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return [{**e.data, "clusters": e.clusters} for e in project_entries(data)] if isinstance(data, dict) else []


def pick_project(state: AppState, project: str | None) -> tuple[str, str | None]:
    """(name, pinned id) of the project to use: --project, or the only project in capella.yaml."""
    projects = file_projects(state)
    if project:
        declared = next((p for p in projects if p.get("name") == project), {})
        return project, declared.get("id")
    if len(projects) == 1:
        return str(projects[0].get("name")), projects[0].get("id")
    if not projects:
        raise CliExit(ExitCode.CONFIG_INVALID, "no project given and no capella.yaml here; pass --project NAME "
                                               "or run 'capellactl sync'", topic="getting-started")
    names = ", ".join(str(p.get("name")) for p in projects)
    raise CliExit(ExitCode.CONFIG_INVALID, f"capella.yaml has several projects ({names}); pass --project NAME")


def cluster_not_project(state: AppState, name: str, command: str) -> str:
    """'' or a hint when NAME is a cluster in capella.yaml rather than a project (e.g. $CLUSTER passed for $PROJECT)."""
    owners = [str(p.get("name")) for p in file_projects(state)
              if any(isinstance(c, dict) and c.get("name") == name for c in p.get("clusters") or [])]
    if len(owners) != 1:
        return ""
    return f"\n{name} is a cluster in project {owners[0]}, not a project. Did you mean: {command.format(owners[0])}"


def project_of_cluster(state: AppState, cluster: str, project: str | None) -> str | None:
    """--project, or the only project in capella.yaml that has a cluster with this name."""
    if project:
        return project
    owners = [str(p.get("name")) for p in file_projects(state)
              if any(isinstance(c, dict) and c.get("name") == cluster for c in p.get("clusters") or [])]
    if len(owners) > 1:
        raise CliExit(ExitCode.CONFIG_INVALID, f"cluster {cluster} is in several projects ({', '.join(owners)}); "
                                               "pass --project NAME")
    return owners[0] if owners else None


def _project_id(state: AppState, client: Any, project: str | None) -> tuple[str, str]:
    name, pinned = pick_project(state, project)
    if pinned:
        return str(pinned), name
    matches = [p for p in ep.list_projects(client) if p.get("name") == name]
    if not matches:
        raise CliExit(ExitCode.ERROR, f"project {name} not found"
                      + cluster_not_project(state, str(name), "project {}"))
    if len(matches) > 1:
        raise CliExit(ExitCode.BLOCKED, f"{len(matches)} projects named {name}; use the project id", topic="idempotency")
    return str(matches[0]["id"]), str(name)


def find_cluster(client: Any, pid: str, name: str) -> dict[str, Any]:
    """The cluster of a project with this name (or id), as listed by Capella."""
    matches = [c for c in ep.list_clusters(client, pid) if c.get("name") == name or c.get("id") == name]
    if not matches:
        raise CliExit(ExitCode.ERROR, f"cluster {name} not found")
    if len(matches) > 1:
        raise CliExit(ExitCode.BLOCKED, f"{len(matches)} clusters named {name}; use the cluster id", topic="idempotency")
    return matches[0]


def file_cluster(state: AppState, cluster: str, project: str | None) -> dict[str, Any] | None:
    """The cluster as capella.yaml declares it (first match; None when it is not in the file)."""
    for p in file_projects(state):
        if project and p.get("name") != project:
            continue
        for c in p.get("clusters") or []:
            if isinstance(c, dict) and c.get("name") == cluster:
                return c
    return None


def live_cluster(state: AppState, cluster: str, project: str | None) -> tuple[Any, str, dict[str, Any]]:
    """(client, project id, cluster body) of a cluster that exists in Capella."""
    client = state.client(_file_org(state))
    pid, _ = _project_id(state, client, project_of_cluster(state, cluster, project))
    return client, pid, find_cluster(client, pid, cluster)


def _file_org(state: AppState) -> str | None:
    try:
        return state.load_config().organization_id
    except CliExit:
        return None


# ------------------------------------------------------------------ project
@click.group(cls=SuggestingGroup, epilog="\b\nExamples:\n  capellactl project list\n"
                    "  capellactl project create nova-qa --description \"QA environment\"\n"
                    "  capellactl project get nova-dev")
def project() -> None:
    """Projects: list, get, create, update, delete."""


@project.command("list")
@pass_state
def project_list(state: AppState) -> None:
    """List projects in the organization."""
    client = state.client(_file_org(state))
    items = ep.list_projects(client)
    if state.json:
        out(dumps(items))
        return
    declared = file_projects(state)
    names = {p.get("name") for p in declared}
    ids = {p.get("id") for p in declared if p.get("id")}
    rows = [("NAME", "DESCRIPTION", "CREATED", "IN FILE", "ID")]
    rows += [(str(p.get("name")), str(p.get("description") or ""), str((p.get("audit") or {}).get("createdAt", "")),
              "yes" if (p.get("id") in ids or p.get("name") in names) else "-", str(p.get("id"))) for p in items]
    out(_list_table(rows))


@project.command("get")
@click.argument("name")
@pass_state
def project_get(state: AppState, name: str) -> None:
    """Show one project."""
    client = state.client(_file_org(state))
    pid, _ = _project_id(state, client, name)
    body, _ = ep.get_project(client, pid)
    if state.json:
        out(dumps(body))
        return
    out(_table([("FIELD", "VALUE")] + [(k, str(body.get(k, ""))) for k in ("id", "name", "description")]))


@project.command("create", epilog="\b\nExamples:\n  capellactl project create nova-qa\n"
                                  "  capellactl --auto-approve project create nova-qa --description \"QA\"\n"
                                  "  capellactl --config envs/qa.yaml project create nova-qa")
@click.argument("name")
@click.option("--description", help="Project description (asked when omitted).")
@pass_state
def project_create(state: AppState, name: str, description: str | None) -> None:
    """Create a project in Capella and add it to capella.yaml (then: capellactl cluster create)."""
    import yaml

    from capellactl.cli import console
    from capellactl.cli.console import err, note
    from capellactl.config.editor import ConfigEditor
    from capellactl.importer import NEW_CLUSTER_TEMPLATE, ImportResult, combine, render

    path = state.config_path()
    editor: ConfigEditor | None = None
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            raw = None
        if not (isinstance(raw, dict) and ("projects" in raw or "project" in raw)):
            raise CliExit(ExitCode.CONFIG_INVALID, f"{path.name} is not a capellactl file; move it away or pass "
                                                   f"--config {name}.yaml", topic="config")
        editor = ConfigEditor(path)
    in_file = editor is not None and name in editor.project_names()

    client = state.client()
    if any(p.get("name") == name for p in ep.list_projects(client)):
        hint = ("it is already in capella.yaml" if in_file
                else f"to add it to capella.yaml run 'capellactl sync --project {name}'")
        raise CliExit(ExitCode.BLOCKED, f"project {name} already exists; {hint}", topic="idempotency")
    interactive = console.is_interactive()
    if description is None and interactive:
        description = console.ask("Description (optional)", "", show_default=False)
    out(f"Project {name} · organization {client.org_id}")
    out("")
    out(f"  + project {name}" + (f"  {description}" if description else ""))
    out("")
    out("Plan: 1 to add, 0 to change, 0 to delete, 0 blocked.")
    verb = "add it to" if editor is not None and not in_file else ("keep" if in_file else "write")
    if not console.confirm(state, f"Create project {name} in Capella and {verb} {path.name}?", "create a project"):
        out("Cancelled; nothing was created.")
        return
    body: dict[str, Any] = {"name": name}
    if description:
        body["description"] = description
    pid = ep.create_project(client, body)
    err(f"project {name} created (id {pid})")
    if in_file:  # the file already describes this project (it may list clusters to deploy)
        out(f"{path.name} already describes {name}; kept as is. Next: capellactl apply")
        return
    if editor is not None:
        editor.add_project({**body, "clusters": []})
        backup = editor.save()
        note(f"previous file saved as {backup}")
        out(f"Added project {name} to {path}.")
    else:
        try:
            org_name = ep.get_organization(client)[0].get("name")
        except Exception:  # noqa: BLE001 - only used in a comment
            org_name = None
        doc = combine([ImportResult(data={"project": dict(body), "clusters": []})], client.org_id)
        text = render(doc, org_name).replace("clusters: []\n", "clusters: []\n" + NEW_CLUSTER_TEMPLATE, 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        out(f"{path} written for project {name}.")
    out(f"Next: capellactl cluster create NAME --project {name}    (deploys the first cluster of this project)")


@project.command("update", epilog="\b\nExamples:\n  capellactl project update nova-dev --description \"Nova dev\"\n"
                                  "  capellactl project update nova-dev --description \"Nova dev\" --no-apply")
@click.argument("name")
@click.option("--description", help="New description (asked when omitted).")
@click.option("--no-apply", is_flag=True, help="Only update capella.yaml; apply later.")
@pass_state
def project_update(state: AppState, name: str, description: str | None, no_apply: bool) -> None:
    """Change a project's description; records it in capella.yaml and applies it."""
    from capellactl.cli import console
    from capellactl.cli.cluster_ops import _ask, change_and_apply, open_editor

    ed = open_editor(state)
    node = ed.find_project(name)
    if node is None:
        hint = cluster_not_project(state, name, "capellactl project update {}" + (
            f' --description "{description}"' if description is not None else ""))
        raise CliExit(ExitCode.CONFIG_INVALID, f"project {name} is not in capella.yaml"
                      + (hint or f"; add it with 'capellactl sync --project {name}'"))
    if description is None:
        if not console.is_interactive():
            raise CliExit(ExitCode.CONFIG_INVALID, "nothing to change; pass --description")
        description = _ask("Description", node.get("description", ""))
    node["description"] = description
    change_and_apply(state, ed, f"project/{name}", f"Record this change in capella.yaml and apply it to {name}?",
                     no_apply, descendants=False)


@project.command("apply", hidden=True)
@click.argument("name", required=False)
@pass_state
def project_apply(state: AppState, name: str | None) -> None:
    """Deprecated alias: apply the project settings recorded in capella.yaml (use 'project update')."""
    project, _ = pick_project(state, name)
    run_apply(state, [f"project/{project}"], descendants=False)


@project.command("delete", epilog="\b\nExamples:\n  capellactl project delete non-prod\n"
                                  "  capellactl project delete non-prod --cascade      (also deletes its clusters)\n"
                                  "  capellactl --auto-approve project delete non-prod")
@click.argument("name")
@click.option("--cascade", is_flag=True, help="Also delete the project's clusters (and wait until they are gone).")
@click.option("--discard-snapshots", is_flag=True, help="With --cascade: do not keep clusters' snapshot backups.")
@pass_state
def project_delete(state: AppState, name: str, cascade: bool, discard_snapshots: bool) -> None:
    """Delete a project from Capella and from capella.yaml (CAP-010)."""
    from capellactl.api.errors import Conflict
    from capellactl.cli import console
    from capellactl.cli.console import note, wait_progress
    from capellactl.engine.clock import get_clock
    from capellactl.engine.waiter import wait_for_cluster
    from capellactl.resources.cluster import is_free
    from capellactl.resources.guards import deletion_protected, protection_message

    client = state.client(_file_org(state))
    declared = next((p for p in file_projects(state) if p.get("name") == name), {})
    projects = ep.list_projects(client)
    matches = [p for p in projects if (p.get("id") == declared["id"] if declared.get("id") else p.get("name") == name)]
    if not matches:
        out(f"project {name} not found, nothing to do")
        _remove_from_file(state, name)
        return
    if len(matches) > 1:
        ids = ", ".join(str(p["id"]) for p in matches)
        raise CliExit(ExitCode.BLOCKED, f"{len(matches)} projects are named {name} (ids: {ids}); pin the one to "
                                        "delete with id: in capella.yaml", topic="idempotency")
    pid = str(matches[0]["id"])
    clusters = ep.list_clusters(client, pid)
    if clusters and not cascade:
        names = ", ".join(str(c.get("name")) for c in clusters)
        noun = "cluster" if len(clusters) == 1 else "clusters"
        raise CliExit(ExitCode.BLOCKED, f"project {name} contains {len(clusters)} {noun} ({names}). Delete "
                                        f"{'it' if len(clusters) == 1 else 'them'} first or pass --cascade.",
                      topic="safety")

    lines = [f"Project {name} · organization {client.org_id}", ""]
    blocked = []
    for c in reversed(clusters):
        if deletion_protected(c):
            blocked.append(c)
            lines.append(f"  ! cluster {c.get('name')}  {protection_message(str(c.get('name')))}")
        else:
            lines.append(f"  - cluster {c.get('name')}")
    lines.append(f"  - project {name}")
    lines += ["", f"Plan: 0 to add, 0 to change, {len(clusters) - len(blocked) + 1} to delete, {len(blocked)} blocked."]
    out("\n".join(lines))
    if blocked:
        raise CliExit(ExitCode.BLOCKED, "Nothing was deleted.", topic="safety")

    notes = (f"This deletes {len(clusters)} cluster(s) and all their data"
             + ("; snapshot backups are discarded" if discard_snapshots else "; snapshot backups are kept") + "."
             if clusters else None)
    if not console.confirm_typed(state, "Type the project name to confirm deletion", "delete a project", name,
                                 notes=notes):
        out("Cancelled; nothing was deleted.")
        return

    clock = get_clock()
    for c in reversed(clusters):
        cid, cname = str(c["id"]), str(c.get("name"))
        free = is_free(c)
        note(f"→ deleting cluster {cname} …")
        if free:
            ep.delete_free_cluster(client, pid, cid)
        else:
            ep.delete_cluster(client, pid, cid, retain_snapshot_backups=not discard_snapshots)
        if not state.no_wait:
            on_state, on_tick = wait_progress(f"cluster {cname}")
            wait_for_cluster(client, pid, cid, "delete", state.timeout, clock, on_state,
                             name=cname, getter=ep.get_free_cluster if free else None, on_tick=on_tick)
    if clusters and state.no_wait:
        out("Clusters are being deleted (--no-wait); run this command again to delete the project when they are gone.")
        return
    try:
        ep.delete_project(client, pid)
    except Conflict as exc:
        msg = "Capella refused: project is not empty"
        if exc.hint:
            msg += f"\nHint: {exc.hint}"
        raise CliExit(ExitCode.ERROR, msg) from None
    out(f"deleted project {name}")
    _remove_from_file(state, name)


def _remove_from_file(state: AppState, name: str) -> None:
    """Keep capella.yaml in step: drop the deleted project (CAP-010 AC8)."""
    from capellactl.cli.console import note
    from capellactl.config.editor import ConfigEditor

    path = state.config_path()
    if not path.exists() or name not in {p.get("name") for p in file_projects(state)}:
        return
    ed = ConfigEditor(path)
    projects = ed.ensure_projects()
    for i, p in enumerate(projects):
        if p.get("name") == name:
            del projects[i]
            break
    backup = ed.save()
    note(f"removed project {name} from {path.name} (previous version kept as {backup.name})")


# ------------------------------------------------------------------ cluster
@click.group(cls=SuggestingGroup, epilog="\b\nExamples:\n  capellactl cluster options\n"
                    "  capellactl cluster create try-01 --free-tier\n  capellactl cluster create nova-dev-02\n"
                    "  capellactl cluster update nova-dev-01 --support-plan enterprise\n"
                    "  capellactl cluster scale nova-dev-01 --nodes 5\n  capellactl cluster list\n"
                    "  capellactl cluster get nova-dev-01")
def cluster() -> None:
    """Clusters: options, disk-types, list, get, create, clone, update, scale, delete, protect, power, schedule, group,
    backup."""


def _cluster_rows(items: list[dict[str, Any]], project: bool = False) -> list[tuple[str, ...]]:
    """Table rows, the cluster's name first; `project=True` adds a PROJECT column after it (items carry projectName)."""
    rows: list[tuple[str, ...]] = [("NAME", *(("PROJECT",) if project else ()), "STATE", "PROVIDER", "REGION", "NODES",
                                    "PLAN", "ID")]
    for c in items:
        cp = c.get("cloudProvider") or {}
        nodes = sum(int(g.get("numOfNodes") or 0) for g in c.get("serviceGroups") or [])
        rows.append((str(c.get("name")), *((str(c.get("projectName")),) if project else ()), str(c.get("currentState")),
                     str(cp.get("type")), str(cp.get("region")), str(nodes),
                     str((c.get("support") or {}).get("plan", "")), str(c.get("id"))))
    return rows


@cluster.command("list", epilog="\b\nExamples:\n  capellactl cluster list\n  capellactl cluster list --project nova-dev")
@click.option("--project", metavar="NAME", help="Only this project (default: every project in the organization).")
@pass_state
def cluster_list(state: AppState, project: str | None) -> None:
    """List clusters of every project in the organization (or of one project)."""
    client = state.client(_file_org(state))
    if project:
        pid, name = _project_id(state, client, project)
        projects = [{"id": pid, "name": name}]
    else:
        projects = sorted(ep.list_projects(client), key=lambda p: str(p.get("name")))
    items = [{**c, "projectId": str(p["id"]), "projectName": str(p.get("name"))}
             for p in projects for c in sorted(ep.list_clusters(client, str(p["id"])), key=lambda c: str(c.get("name")))]
    out(dumps(items) if state.json else _list_table(_cluster_rows(items, project=True)))


@cluster.command("get")
@click.argument("name", shell_complete=complete_cluster_names)
@click.option("--project", metavar="NAME", help="Project name (default: from the config file).")
@pass_state
def cluster_get(state: AppState, name: str, project: str | None) -> None:
    """Show one cluster: state, size, connection string."""
    client = state.client(_file_org(state))
    pid, _ = _project_id(state, client, project_of_cluster(state, name, project))
    body, _ = ep.get_cluster(client, pid, str(find_cluster(client, pid, name)["id"]))
    if state.json:
        out(dumps(body))
        return
    rows = _cluster_rows([body])
    out(_table(rows))
    for g in body.get("serviceGroups") or []:
        node = g.get("node") or {}
        comp, disk = node.get("compute") or {}, node.get("disk") or {}
        out(f"  group {','.join(sorted(g.get('services') or []))}: {g.get('numOfNodes')} × {comp.get('cpu')} vCPU/"
            f"{comp.get('ram')} GB, disk {disk.get('type')} {disk.get('storage', '')}")
    out(f"deletionProtection: {str(body.get('deletionProtection', False)).lower()}   "
        f"expressScaling: {body.get('expressScaling', 'n/a')}")
    if body.get("connectionString"):
        out(f"connectionString: {body['connectionString']}")


@cluster.command("apply", hidden=True)
@click.argument("name", shell_complete=complete_cluster_names)
@click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name repeats).")
@pass_state
def cluster_apply(state: AppState, name: str, project: str | None) -> None:
    """Deprecated alias: apply what capella.yaml records for one cluster (use 'apply --target cluster/NAME')."""
    owner = project_of_cluster(state, name, project)
    run_apply(state, [f"cluster/{owner}/{name}" if owner else f"cluster/{name}"])


@cluster.command("scale", epilog="\b\nExamples:\n  capellactl cluster scale nova-dev-01 --nodes 5\n"
                                 "  capellactl cluster scale nova-dev-01 --nodes 3                   (scale in: capacity checked)\n"
                                 "  capellactl cluster scale nova-dev-01 --nodes 2 --group search\n"
                                 "  capellactl cluster scale nova-dev-01 --step +1 --max 6           (one node more)\n"
                                 "  capellactl cluster scale nova-dev-01 --step -1 --min 3           (one node less)\n"
                                 "  capellactl --auto-approve -o json cluster scale nova-dev-01 --step +1 --all-groups")
@click.argument("name", shell_complete=complete_cluster_names)
@click.option("--nodes", type=click.IntRange(1, 27), help="Target node count for the group.")
@click.option("--group", "group", metavar="SERVICES", help="Group to scale, e.g. data,index,query "
              "(default: the group running data).")
@click.option("--step", metavar="+1|-1", help="Add or remove one node, from the count Capella has now.")
@click.option("--min", "min_nodes", type=int, help="With --step: lowest node count (default: 3 for the first group, "
              "2 for others).")
@click.option("--max", "max_nodes", type=int, help="With --step: highest node count (default: 27 first group, 24 others).")
@click.option("--all-groups", is_flag=True, help="With --step: step every group by one node (each on its own).")
@click.option("--skip-capacity-check", is_flag=True, help="Scale in even when cluster stats cannot be read "
              "(at your own risk).")
@click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name repeats).")
@click.option("--no-apply", is_flag=True, help="Only record the new size in capella.yaml; apply later.")
@pass_state
def cluster_scale(state: AppState, name: str, nodes: int | None, group: str | None, step: str | None,
                  min_nodes: int | None, max_nodes: int | None, all_groups: bool, skip_capacity_check: bool,
                  project: str | None, no_apply: bool) -> None:
    """Scale a service group: records the node count in capella.yaml and applies it.

    Scale-in (fewer nodes) runs capacity checks first: buckets must still fit in memory and every bucket's replicas
    need enough data nodes (CAP-016). --step adds or removes one node within --min/--max (CAP-018); at a limit it
    exits 0 without changing anything.
    """
    from capellactl.cli.cluster_ops import scale_in_file, step_scale

    if step is not None:
        if nodes is not None:
            raise CliExit(ExitCode.CONFIG_INVALID, "pass either --nodes or --step", topic="scaling")
        if step.strip() not in ("+1", "-1", "1"):
            raise CliExit(ExitCode.CONFIG_INVALID, "--step takes +1 or -1", topic="scaling")
        step_scale(state, name, -1 if step.strip() == "-1" else 1, group, min_nodes, max_nodes, all_groups, project,
                   no_apply, skip_capacity_check)
        return
    if min_nodes is not None or max_nodes is not None or all_groups:
        raise CliExit(ExitCode.CONFIG_INVALID, "--min, --max and --all-groups go with --step", topic="scaling")
    if nodes is None:
        raise CliExit(ExitCode.CONFIG_INVALID, "pass --nodes N or --step +1|-1", topic="scaling")
    scale_in_file(state, name, nodes, group, no_apply, project, skip_capacity_check)


def _register_cluster_ops() -> None:
    from capellactl.cli.cluster_lifecycle import cluster_delete, cluster_protect
    from capellactl.cli.cluster_ops import cluster_create, cluster_disk_types, cluster_options, cluster_update

    cluster.add_command(cluster_create)
    cluster.add_command(cluster_update)
    cluster.add_command(cluster_options)
    cluster.add_command(cluster_disk_types)
    cluster.add_command(cluster_delete)
    cluster.add_command(cluster_protect)
    from capellactl.cli.cluster_clone import cluster_clone

    cluster.add_command(cluster_clone)
    from capellactl.cli.power_cmds import cluster_power
    from capellactl.cli.schedule_cmds import schedule

    cluster.add_command(cluster_power)
    cluster.add_command(schedule)
    from capellactl.cli.cluster_group import group

    cluster.add_command(group)
    from capellactl.cli.cluster_backup import backup

    cluster.add_command(backup)


_register_cluster_ops()


def _scope_groups() -> tuple[click.Group, click.Group]:
    from capellactl.cli.scope_cmds import collection, scope

    return scope, collection


scope, collection = _scope_groups()


def _credential_group() -> click.Group:
    from capellactl.cli.credential_cmds import credential

    return credential


credential = _credential_group()


def _bucket_group() -> click.Group:
    from capellactl.cli.bucket_backup import backup as bucket_backup
    from capellactl.cli.bucket_cmds import bucket

    bucket.add_command(bucket_backup)
    return bucket


bucket = _bucket_group()


def _cidr_group() -> click.Group:
    from capellactl.cli.cidr_cmds import cidr

    return cidr


cidr = _cidr_group()

GROUPS = [project, cluster, cidr, bucket, scope, collection, credential]
