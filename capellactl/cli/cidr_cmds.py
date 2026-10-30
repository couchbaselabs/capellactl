"""cidr list | create | delete (CAP-022).

There is no `update`: the API cannot change an allowed CIDR (00-architecture.md section 5 "Verbs"); change
`comment` or `expiresAt` with `apply`, which replaces the entry. create records the entry in capella.yaml and
applies it, like `bucket create`; delete removes it from Capella and from the file.
"""

from __future__ import annotations

import ipaddress
from typing import Any

import click
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from capellactl.api import endpoints as ep
from capellactl.cli import console
from capellactl.cli.cluster_ops import change_and_apply, locate, open_editor
from capellactl.cli.console import note, out
from capellactl.cli.env import pass_state
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.groups import SuggestingGroup
from capellactl.cli.resource_cmds import (
    _list_table,
    complete_cluster_names,
    file_cluster,
    live_cluster,
)
from capellactl.cli.state import AppState
from capellactl.config.crossref import ANY_IP, normalize_cidr
from capellactl.config.editor import put, to_commented
from capellactl.output.render import dumps
from capellactl.resources.allowed_cidr import canonical

PROJECT_OPT = click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name repeats).")


@click.group(cls=SuggestingGroup, epilog="\b\nExamples:\n  capellactl cidr list nova-dev-01\n"
                                         "  capellactl cidr create nova-dev-01 203.0.113.10/32 --comment \"Office VPN\"\n"
                                         "  capellactl cidr delete nova-dev-01 203.0.113.10/32")
def cidr() -> None:
    """Allowed IP ranges: list, create, delete."""


def _strict(value: str) -> str:
    """Canonical CIDR, or exit 3 with the same message as `validate` (CAP-022 AC2)."""
    try:
        return normalize_cidr(value)
    except ValueError:
        try:
            net = ipaddress.ip_network(value.strip(), strict=False)
        except ValueError:
            raise CliExit(ExitCode.CONFIG_INVALID, f"{value} is not a valid CIDR", topic="config",
                                                   action="Give an address and prefix length, for example "
                                                          "203.0.113.10/32 for one address or 10.0.0.0/24 for 256.") from None
        raise CliExit(ExitCode.CONFIG_INVALID, f"{value} is not a network address (did you mean {net}?)",
                      topic="config",
                                               action=f"Use {net} instead: the bits after the prefix length must be "
                                                      f"zero.") from None


def _declared(state: AppState, cluster: str, project: str | None) -> set[str]:
    return {canonical(str(c.get("cidr", ""))) for c in (file_cluster(state, cluster, project) or {}).get("allowedCidrs")
            or [] if isinstance(c, dict)}


@cidr.command("list")
@click.argument("cluster", shell_complete=complete_cluster_names)
@PROJECT_OPT
@pass_state
def cidr_list(state: AppState, cluster: str, project: str | None) -> None:
    """List the IP ranges allowed to connect to a cluster."""
    client, pid, cl = live_cluster(state, cluster, project)
    items = ep.list_allowed_cidrs(client, pid, str(cl["id"]))
    if state.json:
        out(dumps(items))
        return
    declared = _declared(state, cluster, project)
    rows: list[tuple[str, ...]] = [("CIDR", "COMMENT", "EXPIRES", "STATUS", "IN FILE")]
    for c in items:
        rows.append((canonical(str(c.get("cidr", ""))), str(c.get("comment") or ""), str(c.get("expiresAt") or "never"),
                     str(c.get("status") or ""), "yes" if canonical(str(c.get("cidr", ""))) in declared else "-"))
    out(_list_table(rows))


@cidr.command("create", epilog="\b\nExamples:\n  capellactl cidr create nova-dev-01 203.0.113.10/32 --comment \"Office VPN\"\n"
                                "  capellactl cidr create nova-dev-01 198.51.100.0/24 --expires-at 2026-12-31T23:59:59Z\n"
                                "  capellactl cidr create nova-dev-01 203.0.113.10 --no-apply")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("cidr_value", metavar="CIDR")
@click.option("--comment", help="Short description (for example who uses it).")
@click.option("--expires-at", metavar="RFC3339", help="Expiry time, for example 2026-12-31T23:59:59Z (default: permanent).")
@click.option("--allow-any-ip", is_flag=True, help="Required to allow 0.0.0.0/0 (records allowAnyIp: true).")
@PROJECT_OPT
@click.option("--no-apply", is_flag=True, help="Only add the entry to capella.yaml; create it later with apply.")
@pass_state
def cidr_create(state: AppState, cluster: str, cidr_value: str, comment: str | None, expires_at: str | None,
                allow_any_ip: bool, project: str | None, no_apply: bool) -> None:
    """Allow an IP range: records it in capella.yaml and creates it in Capella (an existing one is adopted)."""
    canon = _strict(cidr_value)
    ed = open_editor(state)
    _, cl = locate(ed, cluster, project)
    if any(canonical(str(c.get("cidr", ""))) == canon for c in cl.get("allowedCidrs") or [] if isinstance(c, dict)):
        raise CliExit(ExitCode.BLOCKED, f"{canon} is already in capella.yaml for {cluster}", topic="idempotency",
                                        action=f"To change its comment or expiry, run 'capellactl cidr delete "
                                               f"{cluster} {canon}', then create it again with the new values.")
    entry: dict[str, Any] = {"cidr": canon}
    if comment:
        entry["comment"] = comment
    if expires_at:
        entry["expiresAt"] = expires_at
    if canon in ANY_IP and allow_any_ip:
        put(cl, "allowAnyIp", True)
    if "allowedCidrs" not in cl or not isinstance(cl.get("allowedCidrs"), CommentedSeq):
        put(cl, "allowedCidrs", CommentedSeq())
    cl["allowedCidrs"].append(to_commented(entry))
    change_and_apply(state, ed, f"allowed-cidr/{cluster}/{canon}",
                     f"Add {canon} to capella.yaml and allow it on {cluster}?", no_apply,
                     noop_message=f"{canon} is already allowed on {cluster}; recorded it in capella.yaml")


@cidr.command("delete", epilog="\b\nExamples:\n  capellactl cidr delete nova-dev-01 203.0.113.10/32\n"
                                "  capellactl --auto-approve cidr delete nova-dev-01 203.0.113.10")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("cidr_value", metavar="CIDR")
@PROJECT_OPT
@pass_state
def cidr_delete(state: AppState, cluster: str, cidr_value: str, project: str | None) -> None:
    """Stop allowing an IP range: deletes it from Capella and removes it from capella.yaml."""
    canon = canonical(cidr_value)
    client, pid, cl = live_cluster(state, cluster, project)
    cid = str(cl["id"])
    found = [c for c in ep.list_allowed_cidrs(client, pid, cid) if canonical(str(c.get("cidr", ""))) == canon]
    if not found:
        out(f"allowed CIDR {canon} on {cluster} not found, nothing to do")
        _remove_from_file(state, cluster, canon, project)
        return
    out(f"  - allowed-cidr {cluster}/{canon}" + (f'  "{found[0]["comment"]}"' if found[0].get("comment") else ""))
    if not console.confirm(state, f"Connections from {canon} to {cluster} will be refused. Delete it?",
                           "delete an allowed CIDR"):
        out("Cancelled; nothing was deleted.")
        return
    for entry in found:
        ep.delete_allowed_cidr(client, pid, cid, str(entry["id"]))
    out(f"deleted allowed CIDR {canon} from {cluster}")
    _remove_from_file(state, cluster, canon, project)


def _remove_from_file(state: AppState, cluster: str, canon: str, project: str | None) -> None:
    """Keep capella.yaml in step, so the next apply does not allow the range again."""
    from capellactl.config.editor import ConfigEditor

    path = state.config_path()
    if not path.exists() or canon not in _declared(state, cluster, project):
        return
    ed = ConfigEditor(path)
    try:
        found = ed.find_cluster(cluster, project)
    except LookupError:
        return
    if found is None:
        return
    seq = found[1].get("allowedCidrs") or []
    for i, c in enumerate(seq):
        if isinstance(c, CommentedMap) and canonical(str(c.get("cidr", ""))) == canon:
            del seq[i]
            break
    if not seq:
        del found[1]["allowedCidrs"]
    backup = ed.save()
    note(f"removed {canon} from {path.name} (previous version kept as {backup.name})")
