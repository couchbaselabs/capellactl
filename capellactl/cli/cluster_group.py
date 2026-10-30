"""capellactl cluster group list|add|remove: change a cluster's service layout from the CLI (CAP-052).

Adding a group is a scale out (CAP-015) and removing one a guarded scale in (CAP-016); both go through the same
validate → plan → confirm → write → apply path as every cluster command, so capella.yaml is never edited by hand.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import click

from capellactl.cli import console
from capellactl.cli.cluster_ops import (
    _ask_disk,
    change_and_apply,
    locate,
    make_disk,
    open_editor,
    parse_services,
)
from capellactl.cli.console import out
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.groups import SuggestingGroup
from capellactl.cli.resource_cmds import _list_table, complete_cluster_names, live_cluster
from capellactl.cli.state import AppState
from capellactl.config.editor import to_commented
from capellactl.engine.normalize import group_key
from capellactl.output.render import dumps

PROJECT_OPT = click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name repeats).")
NO_APPLY_OPT = click.option("--no-apply", is_flag=True, help="Only update capella.yaml; apply later.")


@click.group("group", cls=SuggestingGroup, epilog="\b\nExamples:\n"
             "  capellactl cluster group list nova-prod-01\n"
             "  capellactl cluster group add nova-prod-01 --services search --nodes 2\n"
             "  capellactl cluster group add nova-prod-01 --services index,query --nodes 2 --cpu 16 --ram 64\n"
             "  capellactl cluster group remove nova-prod-01 search")
def group() -> None:
    """Service groups (multi-dimensional scaling): list, add, remove. Change a group's size with 'cluster scale
    --group' (nodes) and 'cluster update --group' (compute, disk)."""


def _plain(node: Any) -> Any:
    return json.loads(json.dumps(node))


def _disk_text(disk: dict[str, Any]) -> str:
    parts = [str(disk.get("type", ""))]
    if disk.get("storage"):
        parts.append(f"{disk['storage']} GB")
    if disk.get("iops"):
        parts.append(f"{disk['iops']} IOPS")
    if disk.get("autoExpansion"):
        parts.append("auto-expansion")
    return " ".join(p for p in parts if p)


@group.command("list", epilog="\b\nExamples:\n  capellactl cluster group list nova-prod-01\n"
                              "  capellactl -o json cluster group list nova-prod-01")
@click.argument("name", shell_complete=complete_cluster_names)
@PROJECT_OPT
@click.pass_obj
def group_list(state: AppState, name: str, project: str | None) -> None:
    """List a cluster's service groups as Capella reports them."""
    from capellactl.api import endpoints as ep

    client, pid, listed = live_cluster(state, name, project)
    body, _ = ep.get_cluster(client, pid, str(listed["id"]))
    groups = body.get("serviceGroups") or []
    if state.json:
        out(dumps(groups))
        return
    rows = [("SERVICES", "NODES", "vCPU", "RAM GB", "DISK")]
    for g in groups:
        node = g.get("node") or {}
        comp = node.get("compute") or {}
        rows.append((group_key(g), str(g.get("numOfNodes")), str(comp.get("cpu")), str(comp.get("ram")),
                     _disk_text(node.get("disk") or {})))
    out(_list_table(rows))
    out(f"total nodes: {sum(int(g.get('numOfNodes') or 0) for g in groups)} of 27")


@group.command("add", epilog="\b\nExamples:\n  capellactl cluster group add nova-prod-01 --services search --nodes 2\n"
                             "  capellactl cluster group add nova-prod-01 --services index,query --nodes 2 --cpu 16 "
                             "--ram 64 --disk-size 100\n"
                             "Options not given are copied from the group that runs data.")
@click.argument("name", shell_complete=complete_cluster_names)
@click.option("--services", metavar="SERVICES", help="Comma-separated services of the new group (asked).")
@click.option("--nodes", type=int, help="Nodes in the group (asked; default 2, the minimum for an extra group).")
@click.option("--cpu", type=int, help="vCPUs per node (default: as the data group).")
@click.option("--ram", type=int, help="RAM GB per node (default: as the data group).")
@click.option("--disk-type", help="Disk type (default: as the data group; see 'capellactl cluster disk-types').")
@click.option("--disk-size", type=int, help="Disk GB per node (default: as the data group).")
@click.option("--disk-iops", type=int, help="Disk IOPS (AWS; default: as the data group).")
@click.option("--disk-auto-expansion/--no-disk-auto-expansion", default=None,
              help="Azure: let disk storage expand automatically.")
@PROJECT_OPT
@NO_APPLY_OPT
@click.pass_obj
def group_add(state: AppState, name: str, services: str | None, nodes: int | None, cpu: int | None, ram: int | None,
              disk_type: str | None, disk_size: int | None, disk_iops: int | None, disk_auto_expansion: bool | None,
              project: str | None, no_apply: bool) -> None:
    """Add a service group to a cluster (scale out): records it in capella.yaml and applies it."""
    ed = open_editor(state)
    proj_node, cl = locate(ed, name, project)
    if cl.get("tier") == "free":
        raise CliExit(ExitCode.BLOCKED, "free-tier clusters have 1 node and a fixed size", topic="scaling",
                                        action="Create a provisioned cluster to add service groups ('capellactl "
                                               "cluster create NAME').")
    if cl.get("configurationType") == "singleNode":
        raise CliExit(ExitCode.CONFIG_INVALID, "singleNode clusters have exactly one service group", topic="scaling",
                                               action="Create a multiNode cluster to add groups ('capellactl "
                                                      "cluster create NAME --group …').")
    if services is None:
        services = console.ask("Services of the new group", flag="--services")
    names = parse_services(str(services), "--services")
    key = ",".join(names)
    groups = cl.get("serviceGroups") or []
    existing = next((g for g in groups if group_key(g) == key), None)
    if existing is not None:
        comp = existing["node"]["compute"]
        same = all(want is None or want == have for want, have in
                   ((nodes, existing.get("numOfNodes")), (cpu, comp.get("cpu")), (ram, comp.get("ram"))))
        if not same:
            raise CliExit(ExitCode.CONFIG_INVALID, f"group {key} already exists with {existing.get('numOfNodes')} × "
                                                   f"{comp.get('cpu')}/{comp.get('ram')}", topic="scaling",
                                                   action=f"Change its node count with 'capellactl cluster scale "
                                                          f"{name} --group {key} --nodes N', or its size with "
                                                          f"'capellactl cluster update {name} --group {key}'.")
        out(f"group {key} already exists on {name}; nothing to add")
        return
    if nodes is None:
        nodes = int(console.ask("Nodes", 2, type=int)) if console.is_interactive() else 2
    base = next((g for g in groups if "data" in (g.get("services") or [])), groups[0] if groups else None)
    provider = str((cl.get("cloudProvider") or {}).get("type", "aws"))
    base_node = _plain(base["node"]) if base is not None else {"compute": {"cpu": 4, "ram": 16},
                                                               "disk": make_disk(provider)}
    if disk_type:
        disk = make_disk(provider, disk_type, disk_size, disk_iops)
    elif disk_size is None and disk_iops is None and console.is_interactive():
        disk = _ask_disk(provider, copy.deepcopy(base_node["disk"]))  # CAP-060 AC2: default is the data group's
    else:
        disk = copy.deepcopy(base_node["disk"])
        for k, v in (("storage", disk_size), ("iops", disk_iops)):
            if v is not None:
                disk[k] = v
    if disk_auto_expansion is not None:
        disk["autoExpansion"] = disk_auto_expansion
    new = {"node": {"compute": {"cpu": cpu or base_node["compute"]["cpu"], "ram": ram or base_node["compute"]["ram"]},
                    "disk": disk},
           "numOfNodes": nodes, "services": names}
    groups.append(to_commented(new))
    from capellactl.cli.cluster_ops import size_warnings

    change_and_apply(state, ed, f"cluster/{proj_node.get('name')}/{name}",
                     f"Add service group {key} to {name} and record it in capella.yaml?", no_apply,
                     after_plan=size_warnings(provider, [new], single=False))


@group.command("remove", epilog="\b\nExamples:\n  capellactl cluster group remove nova-prod-01 search\n"
                                "  capellactl --auto-approve cluster group remove nova-prod-01 analytics "
                                "--allow-service-removal")
@click.argument("name", shell_complete=complete_cluster_names)
@click.argument("services")
@click.option("--allow-service-removal", is_flag=True, help="Allow removing the last nodes that run a service.")
@click.option("--skip-capacity-check", is_flag=True, help="Remove even when cluster stats cannot be read "
              "(at your own risk).")
@PROJECT_OPT
@NO_APPLY_OPT
@click.pass_obj
def group_remove(state: AppState, name: str, services: str, allow_service_removal: bool, skip_capacity_check: bool,
                 project: str | None, no_apply: bool) -> None:
    """Remove a service group (scale in, with the capacity checks): records it in capella.yaml and applies it."""
    ed = open_editor(state)
    proj_node, cl = locate(ed, name, project)
    if cl.get("tier") == "free":
        raise CliExit(ExitCode.BLOCKED, "free-tier clusters have 1 node and a fixed size", topic="scaling",
                                        action="None needed: a free-tier cluster has no groups to remove.")
    key = ",".join(parse_services(services, "SERVICES"))
    groups = cl.get("serviceGroups") or []
    target = next((g for g in groups if group_key(g) == key), None)
    if target is None:
        out(f"no service group '{key}' (groups: {' · '.join(group_key(g) for g in groups)}); nothing to remove")
        return
    others = [g for g in groups if g is not target]
    if "data" in (target.get("services") or []) and not any("data" in (g.get("services") or []) for g in others):
        raise CliExit(ExitCode.BLOCKED, "the last group running data cannot be removed", topic="scaling",
                                        action="Every cluster needs a group that runs data. To replace this one, "
                                               "add the new data group first ('capellactl cluster group add'), then "
                                               "remove this one.")
    groups.remove(target)
    change_and_apply(state, ed, f"cluster/{proj_node.get('name')}/{name}",
                     f"Remove service group {key} from {name} and record it in capella.yaml?", no_apply,
                     allow_service_group_removal=True, allow_service_removal=allow_service_removal,
                     skip_capacity_check=skip_capacity_check)
