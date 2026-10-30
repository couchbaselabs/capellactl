"""cluster clone (CAP-049): deploy a copy of an existing cluster in another region.

The source is read live from Capella with the import exporters (CAP-036), changed for the new region, recorded in
capella.yaml and deployed through the same path as `cluster create` (CAP-038): validate → plan → ask once → write →
apply, with the file restored when Capella rejects the create.
"""

from __future__ import annotations

import ipaddress
from typing import Any

import click

from capellactl.api import endpoints as ep
from capellactl.cli import console
from capellactl.cli.cluster_ops import (
    SUPPORT_PLANS,
    _org_client,
    _record_server_version,
    _validate_candidate,
    change_and_apply,
    open_editor,
    suggest_cidr,
)
from capellactl.cli.console import out
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.state import AppState
from capellactl.config.editor import ConfigEditor
from capellactl.resources.cluster import create_summary, is_free

CLONABLE_STATES = ("healthy", "turnedOff")
NOT_COPIED_ALWAYS = ["documents", "hibernation schedule"]


def _projects_and_clusters(client: Any) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    return [(p, ep.list_clusters(client, str(p["id"]))) for p in ep.list_projects(client)]


def _choose(label: str, items: list[Any], describe: Any, flag: str) -> Any:
    for i, item in enumerate(items, 1):
        out(f"  {i}. {describe(item)}")
    idx = int(console.ask(label, flag=flag, type=click.IntRange(1, len(items))))
    return items[idx - 1]


def _cluster_line(c: dict[str, Any]) -> str:
    return f"{c.get('name')}  {create_summary(c)}"


def find_source(client: Any, name: str | None, project: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """(project, cluster) of the source, asking when a terminal is attached and something is missing."""
    org = _projects_and_clusters(client)
    if project:
        org = [(p, cs) for p, cs in org if p.get("name") == project]
        if not org:
            raise CliExit(ExitCode.CONFIG_INVALID, f"project {project} not found in Capella",
                                                   action="Check the name with 'capellactl project list', then run "
                                                          "the command again.")
    if name is None:
        if not console.is_interactive():
            raise CliExit(ExitCode.CONFIG_INVALID, "missing SOURCE: there is no terminal to ask for it",
                                                   action="Give the cluster to copy: 'capellactl cluster clone "
                                                          "SOURCE NEW_NAME --region REGION'.")
        with_clusters = [(p, cs) for p, cs in org if cs]
        if not with_clusters:
            raise CliExit(ExitCode.ERROR, "this organization has no clusters to clone",
                                          action="Create a cluster first with 'capellactl cluster create NAME'.")
        if len(with_clusters) == 1:
            p, cs = with_clusters[0]
        else:
            out("Projects:")
            p, cs = _choose("Source project", with_clusters, lambda pc: pc[0].get("name"), "--project")
        out(f"Clusters in {p.get('name')}:")
        return p, _choose("Source cluster", cs, _cluster_line, "SOURCE")
    found = [(p, c) for p, cs in org for c in cs if c.get("name") == name]
    if not found:
        where = f" in project {project}" if project else ""
        raise CliExit(ExitCode.CONFIG_INVALID, f"cluster {name} not found{where}",
                                               action="Check the name with 'capellactl cluster list', then run the "
                                                      "command again.")
    if len(found) > 1:
        names = ", ".join(sorted({str(p.get("name")) for p, _ in found}))
        if not console.is_interactive():
            raise CliExit(ExitCode.CONFIG_INVALID, f"several clusters are named {name} (projects {names})",
                                                   action="Add --project NAME to choose one.")
        out(f"Several clusters are named {name}:")
        chosen: tuple[dict[str, Any], dict[str, Any]] = _choose(
            "Source cluster", found, lambda pc: f"{pc[0].get('name')} / {_cluster_line(pc[1])}", "--project")
        return chosen
    return found[0]


def _ensure_target_project(state: AppState, ed: ConfigEditor, client: Any, name: str) -> ConfigEditor:
    """The target project in capella.yaml: added from Capella like `import --project` when only Capella has it."""
    if name in ed.project_names():
        return ed
    if not any(p.get("name") == name for p in ep.list_projects(client)):
        raise CliExit(ExitCode.CONFIG_INVALID, f"project {name} does not exist",
                                               action=f"Create it first with 'capellactl project create {name}'.")
    from capellactl.cli.env import run_import

    run_import(state, client, projects=(name,))
    return ConfigEditor(ed.path)


def _file_passwords(ed: ConfigEditor, cluster: str, project: str) -> dict[str, str]:
    """Password references of the source cluster's credentials in capella.yaml (kept on the clone)."""
    try:
        found = ed.find_cluster(cluster, project)
    except LookupError:
        return {}
    if found is None:
        return {}
    return {str(c.get("name")): str(c["password"]) for c in found[1].get("databaseCredentials") or []
            if isinstance(c, dict) and c.get("password")}


def _plain(obj: Any) -> Any:
    """The importer's document without its comment and block placeholders."""
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items() if not str(k).startswith("__")}
    if isinstance(obj, list):
        return [_plain(v) for v in obj if not (isinstance(v, dict) and all(str(k).startswith("__") for k in v))]
    return obj


def _overlap(cidr: str, used: list[tuple[str, str]]) -> str | None:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return None  # validation reports it
    for who, other in used:
        try:
            if net.overlaps(ipaddress.ip_network(other, strict=False)):
                return f"{cidr} overlaps the network of cluster {who} ({other})"
        except ValueError:
            continue
    return None


def build_clone(source: dict[str, Any], new_name: str, region: str, cidr: str, description: str,
                support_plan: str | None, server_version: str | None, data_model: bool, with_cidrs: bool,
                with_credentials: bool, passwords: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    """The clone's capella.yaml entry from the source's imported entry, and what was not copied."""
    src = _plain(source)
    clone: dict[str, Any] = {"name": new_name, "description": description}
    if "configurationType" in src:
        clone["configurationType"] = src["configurationType"]
    cp = src.get("cloudProvider") or {}
    clone["cloudProvider"] = {"type": cp.get("type"), "region": region, "cidr": cidr}
    if server_version != "latest":
        version = server_version or (src.get("couchbaseServer") or {}).get("version")
        if version:
            clone["couchbaseServer"] = {"version": version}
    for key in ("availability", "support", "serviceGroups"):
        if key in src:
            clone[key] = src[key]
    if support_plan:
        clone["support"] = {**(clone.get("support") or {}), "plan": support_plan}
    if src.get("deletionProtection"):
        clone["deletionProtection"] = True
    not_copied = list(NOT_COPIED_ALWAYS)
    for key, what in (("cmekId", "customer-managed encryption key"),
                      ("enablePrivateDNSResolution", "private DNS resolution")):
        if src.get(key):
            not_copied.append(what)
    if with_cidrs and src.get("allowedCidrs"):
        source_name = str(source.get("name"))
        clone["allowedCidrs"] = [{**c, "comment": f"{c['comment']} (cloned from {source_name})" if c.get("comment")
                                  else f"(cloned from {source_name})"} for c in src["allowedCidrs"]]
    elif not with_cidrs:
        not_copied.append("allowed CIDRs")
    if data_model and src.get("buckets"):
        clone["buckets"] = src["buckets"]
    if with_credentials and src.get("databaseCredentials"):
        clone["databaseCredentials"] = [{"name": c["name"], **({"password": passwords[c["name"]]}
                                                              if c["name"] in passwords else {}),
                                         "access": c.get("access") or []} for c in src["databaseCredentials"]]
    elif not with_credentials:
        not_copied.append("database credentials")
    return clone, not_copied


@click.command("clone", epilog="\b\nExamples:\n"
                               "  capellactl cluster clone                                  (asks for everything)\n"
                               "  capellactl cluster clone nova-demo-01 nova-demo-weu --region westeurope\n"
                               "  capellactl cluster clone nova-demo-01 nova-dr-01 --region westus2 "
                               "--to-project nova-dr --support-plan 'developer pro'")
@click.argument("source", required=False)
@click.argument("new_name", required=False)
@click.option("--region", help="Region of the clone (asked; required without a terminal).")
@click.option("--project", metavar="NAME", help="Project of SOURCE (only needed when the name repeats).")
@click.option("--to-project", metavar="NAME", help="Project of the clone (default: the source's project).")
@click.option("--cidr", help="Network CIDR of the clone (default: the first free 10.x.y.0/24).")
@click.option("--support-plan", type=click.Choice(SUPPORT_PLANS), help="Support plan (default: the source's).")
@click.option("--server-version", metavar="VERSION", help="Couchbase Server version (default: the source's; "
              "'latest' lets Capella choose).")
@click.option("--description", help="Description (default: 'Clone of SOURCE (PROJECT, REGION)').")
@click.option("--with-cidrs", is_flag=True, help="Also copy the allowed CIDRs.")
@click.option("--with-credentials", is_flag=True, help="Also copy the database credentials (new passwords).")
@click.option("--no-data-model", is_flag=True, help="Do not copy buckets, scopes and collections.")
@click.option("--no-apply", is_flag=True, help="Only add the clone to capella.yaml; deploy later with apply.")
@click.pass_obj
def cluster_clone(state: AppState, source: str | None, new_name: str | None, region: str | None,
                  project: str | None, to_project: str | None, cidr: str | None, support_plan: str | None,
                  server_version: str | None, description: str | None, with_cidrs: bool, with_credentials: bool,
                  no_data_model: bool, no_apply: bool) -> None:
    """Deploy a copy of a cluster in another region: size, services, buckets, scopes and collections."""
    from capellactl.importer import build_document

    ed = open_editor(state)
    client = _org_client(state, ed)
    src_project, src = find_source(client, source, project)
    name, pname = str(src.get("name")), str(src_project.get("name"))
    if is_free(src):
        raise CliExit(ExitCode.BLOCKED, "free-tier clusters cannot be cloned (one per organization)",
                                        action="Create a provisioned cluster with 'capellactl cluster create' "
                                               "instead.")
    if src.get("currentState") not in CLONABLE_STATES:
        raise CliExit(ExitCode.BLOCKED, f"cluster {name} is {src.get('currentState')}",
                                        action=f"Wait until it is healthy ('capellactl cluster get {name}' shows its "
                                               f"state), then run the command again.")
    src_cp = src.get("cloudProvider") or {}
    provider, src_region = str(src_cp.get("type")), str(src_cp.get("region"))

    if region is None:
        region = str(console.ask(f"Region for the clone ({provider}; {name} is in {src_region})", flag="--region"))
    region = region.strip()
    if new_name is None:
        new_name = str(console.ask("Name of the clone", f"{name}-{region}", flag="NEW_NAME"))
    if to_project is None and console.is_interactive() and source is None:
        to_project = str(console.ask("Project of the clone", pname))
    target = to_project or pname

    ed = _ensure_target_project(state, ed, client, target)
    proj_node = ed.find_project(target)
    assert proj_node is not None
    target_capella = next((p for p in ep.list_projects(client) if p.get("name") == target), None)
    target_clusters = ep.list_clusters(client, str(target_capella["id"])) if target_capella else []
    in_file = [c for c in proj_node.get("clusters") or [] if isinstance(c, dict)]
    if any(c.get("name") == new_name for c in [*target_clusters, *in_file]):
        raise CliExit(ExitCode.BLOCKED, f"cluster {new_name} already exists in project {target}",
                                        action="Choose another name for the copy.")

    used = [(str(c.get("name")), str((c.get("cloudProvider") or {}).get("cidr", "")))
            for c in [*target_clusters, *in_file, *ep.list_clusters(client, str(src_project["id"]))]]
    if cidr is None:
        default = suggest_cidr([u for _, u in used])
        cidr = str(console.ask("Network CIDR (must not overlap other clusters)", default)) \
            if console.is_interactive() and source is None else default
    clash = _overlap(cidr, used)
    if clash:
        raise CliExit(ExitCode.CONFIG_INVALID, clash,
                                               action="Pass --cidr with a free range, or leave it out to get one "
                                                      "that does not overlap.")

    if region == src_region and target == pname and not console.confirm(
            state, f"{new_name} would be in the same region and project as {name}. Clone into the same region?",
            "clone into the same region"):
        out("Cancelled; nothing was changed.")
        return

    doc = build_document(client, src_project, [src])
    entry = doc.data["clusters"][0]
    clone, not_copied = build_clone(
        entry, new_name, region, cidr, description or f"Clone of {name} ({pname}, {src_region})", support_plan,
        server_version, not no_data_model, with_cidrs, with_credentials, _file_passwords(ed, name, pname))

    ed.add_cluster(proj_node, clone)
    seq = ed.clusters(proj_node)
    seq.yaml_set_comment_before_after_key(len(seq) - 1, before=f"cloned from {name} ({pname}, {src_region})",
                                          indent=_item_indent(ed))
    text = ed.text()
    _validate_candidate(state, ed, text)
    if not state.json:
        out(f"Cloning {name} ({pname} · {provider} {src_region}) → {new_name} ({target} · {provider} {region})")
    try:
        plan, ctx = change_and_apply(state, ed, f"cluster/{target}/{new_name}",
                                     f"Add {new_name} to capella.yaml and deploy it now?", no_apply, text,
                                     after_plan=["", f"not copied: {', '.join(not_copied)}",
                                                 f"Add a schedule later: capellactl cluster schedule set {new_name} "
                                                 "--timezone TZ --weekdays HH:MM-HH:MM"])
    except CliExit as exc:
        version = (clone.get("couchbaseServer") or {}).get("version")
        if exc.code is ExitCode.ERROR and version and f"Failed: cluster {new_name}" in exc.message:
            exc.message += (f"\nIf Couchbase Server {version} is not offered in {region}, run the command again with "
                            "--server-version latest.")
        raise
    if plan is not None and ctx is not None:
        _record_server_version(ed, new_name, target, plan, ctx)


def _item_indent(ed: ConfigEditor) -> int:
    """Column of a cluster item (the comment goes on the line above it); see ConfigEditor's indentation."""
    return 6 if "projects" in ed.doc else 2
