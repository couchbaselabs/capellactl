"""Change clusters through commands, never by hand-editing capella.yaml (CAP-038).

Every command: change the file in memory → validate it like `capellactl validate` → show the plan →
ask once → write capella.yaml (keeping a .bak) → apply. A blocked or invalid change writes nothing.
"""

from __future__ import annotations

import contextlib
import ipaddress
import os
from typing import Any

import click

from capellactl.api import endpoints as ep
from capellactl.api.errors import TransportError
from capellactl.cli import console
from capellactl.cli.console import err, note, out
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.state import AppState
from capellactl.config.editor import ConfigEditor, put
from capellactl.config.loader import Config, ConfigError, load_config
from capellactl.config.presets import is_single_node, load_presets
from capellactl.engine.planner import build_plan
from capellactl.output.render import render_plan_text
from capellactl.resources.base import Plan, PlanError
from capellactl.resources.cluster import fixed_size_disk

PROVIDERS = ["aws", "gcp", "azure"]
REGION_DEFAULT = {"aws": "us-east-1", "gcp": "us-east1", "azure": "eastus"}
DISK_DEFAULT: dict[str, dict[str, Any]] = {
    "aws": {"type": "gp3", "storage": 50, "iops": 3000},
    "gcp": {"type": "pd-ssd", "storage": 50},
    "azure": {"type": "P6"},
}
# Sizes come from config/presets.yaml (shared with `capellactl init`).
PRESETS: dict[str, dict[str, Any]] = {
    k: {"nodes": v["numOfNodes"], "cpu": v["cpu"], "ram": v["ram"], **({"single": True} if is_single_node(v) else {})}
    for k, v in load_presets().items()
}
SUPPORT_PLANS = ["basic", "developer pro", "enterprise"]
FREE_FIXED = "free-tier clusters have 1 node and fixed size; create a provisioned cluster for that"
FREE_TIER_NOTE = "1 node · data, index, query, search · no cost · one per organization"
FREE_TIER_MISSING = "backups, private endpoints, network peering, audit logs, alert integrations, CMEK, on/off schedule"
TIMEZONES = ["ET", "GMT", "IST", "PT"]


# ------------------------------------------------------------------ helpers
def suggest_cidr(used: list[str]) -> str:
    """First free 10.x.y.0/24 (in address order) that overlaps none of `used`. Capella sets no size rule;
    /24 is what multi-AZ production clusters use and leaves room for more clusters (CAP-038 AC3)."""
    nets = []
    for c in used:
        try:
            nets.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            continue
    for cand in ipaddress.ip_network("10.0.0.0/8").subnets(new_prefix=24):
        if not any(cand.overlaps(u) for u in nets):
            return str(cand)
    return "10.255.255.0/24"


def _org_client(state: AppState, ed: ConfigEditor | None) -> Any:
    org = ed.doc.get("organizationId") if ed is not None else None
    return state.client(org if isinstance(org, str) and not org.startswith("${") else None)


def org_clusters(client: Any) -> list[tuple[str, dict[str, Any]]]:
    """(project name, cluster) for every cluster in the organization."""
    found: list[tuple[str, dict[str, Any]]] = []
    for p in ep.list_projects(client):
        for c in ep.list_clusters(client, str(p["id"])):
            found.append((str(p.get("name")), c))
    return found


def free_tier_in_use(client: Any, ed: ConfigEditor | None) -> str | None:
    """Who already uses the organization's one free-tier cluster, or None when it is available."""
    from capellactl.resources.cluster import is_free

    for project, c in org_clusters(client):
        if is_free(c):
            return f"{c.get('name')} in project {project}"
    if ed is not None:
        for p in ed.ensure_projects():
            for c in p.get("clusters") or []:
                if isinstance(c, dict) and c.get("tier") == "free":
                    return f"{c.get('name')} in project {p.get('name')} (in capella.yaml)"
    return None


def choose_project(ed: ConfigEditor, project: str | None, interactive: bool) -> str:
    """--project, the only project in the file, or ask (CAP-040 AC7)."""
    names = ed.project_names()
    if project:
        if project not in names:
            try:
                owner = ed.find_cluster(project)
            except LookupError:
                owner = None
            if owner is not None:
                raise CliExit(ExitCode.CONFIG_INVALID, f"project {project} is not in capella.yaml\n{project} is a "
                              f"cluster in project {owner[0].get('name')}, not a project. Did you mean: "
                              f"--project {owner[0].get('name')}")
            raise CliExit(ExitCode.CONFIG_INVALID, f"project {project} is not in capella.yaml; create it with "
                          f"'capellactl project create {project}' or add it with 'capellactl import --project {project}'")
        return project
    if len(names) == 1:
        return names[0]
    if not names:
        raise CliExit(ExitCode.CONFIG_INVALID, "capella.yaml has no project; run 'capellactl project create NAME'")
    if not interactive:
        raise CliExit(ExitCode.CONFIG_INVALID, f"capella.yaml has several projects ({', '.join(names)}); "
                                               "pass --project NAME")
    out("Projects in capella.yaml:")
    for i, n in enumerate(names, 1):
        out(f"  {i}. {n}")
    idx = int(console.ask("Which project?", flag="--project", type=click.IntRange(1, len(names))))
    return names[idx - 1]


def locate(ed: ConfigEditor, name: str, project: str | None) -> tuple[Any, Any]:
    try:
        found = ed.find_cluster(name, project)
    except LookupError as exc:
        raise CliExit(ExitCode.CONFIG_INVALID, str(exc)) from None
    if found is None:
        where = f" (project {project})" if project else ""
        raise CliExit(ExitCode.CONFIG_INVALID, f"cluster {name}{where} is not in capella.yaml; run 'capellactl sync' "
                                               "to add it")
    return found


def _ask(text: str, default: Any, choices: list[str] | None = None, kind: Any = str) -> Any:
    t = click.Choice(choices) if choices else kind
    return console.ask(text, default, type=t, show_choices=bool(choices))


def open_editor(state: AppState) -> ConfigEditor:
    path = state.config_path()
    if not path.exists():
        raise CliExit(ExitCode.CONFIG_INVALID, f"{path} not found; run 'capellactl import' (or 'capellactl configure') "
                                               "to create it from your Capella project", topic="getting-started")
    return ConfigEditor(path)


def _validate_candidate(state: AppState, ed: ConfigEditor, text: str) -> Config:
    tmp = ed.path.with_name(f".{ed.path.name}.candidate-{os.getpid()}")
    try:
        tmp.write_text(text, encoding="utf-8")
        cfg = load_config(tmp, env=state.env)
    except ConfigError as exc:
        topic = exc.issues[0].topic if exc.issues else "config"
        raise CliExit(ExitCode.CONFIG_INVALID, str(exc).replace(tmp.name, ed.path.name), topic=topic) from None
    finally:
        tmp.unlink(missing_ok=True)
    cfg.path = ed.path
    return cfg


def change_and_apply(state: AppState, ed: ConfigEditor, target: str, question: str, no_apply: bool,
                     text: str | None = None, noop_message: str | None = None,
                     descendants: bool = True, rotate_passwords: bool = False,
                     after_plan: list[str] | None = None, **options: bool) -> tuple[Plan | None, Any]:
    """Validate → plan → confirm → write → apply. Returns (plan, ctx) or (None, None) when nothing ran.

    `after_plan`: lines shown under the plan, before the question. `options`: RunContext switches (power_on,
    allow_service_removal, skip_capacity_check …)."""
    from capellactl.cli import env as env_mod

    text = text if text is not None else ed.text()
    cfg = _validate_candidate(state, ed, text)
    client = state.client(cfg.organization_id)
    ctx = state.run_context(client, cfg)
    ctx.rotate_passwords = rotate_passwords
    for k, v in options.items():
        setattr(ctx, k, v)
    try:
        plan = build_plan(ctx, cfg, env_mod.TREE_FACTORY(), [target], descendants)
    except PlanError as exc:
        raise CliExit(ExitCode.ERROR, str(exc)) from None
    if not plan.has_changes and not plan.blocked:
        if text != ed.original:
            ed.save(text)
        out(noop_message or "No changes: capella.yaml and Capella already match.")
        return None, None
    if not state.json:  # -o json: the plan is part of the one JSON document printed after apply
        out(render_plan_text(plan, env_mod.plan_header(cfg, client), quiet=console.is_quiet()))
        for line in after_plan or []:
            out(line)
    if plan.blocked:
        raise CliExit(ExitCode.BLOCKED, "Nothing was written to capella.yaml or changed in Capella.",
                      topic=plan.blocked[0].topic)
    if not console.confirm(state, question, "change capella.yaml and Capella"):
        out("Cancelled; capella.yaml and Capella are unchanged.")
        return None, None
    previous = ed.original
    if text != ed.original:
        backup = ed.save(text)
        note(f"{ed.path.name} updated (previous version kept as {backup.name})")
    if no_apply:
        out("Not applied (--no-apply). Run 'capellactl apply' to deploy it.")
        return None, None
    writes_before = client.writes_accepted

    def restore(result: Any) -> str | None:
        # Capella accepted nothing, so the file must not describe what was never made: put it back. Kept when a
        # write may have landed (accepted, connection lost mid-request, or interrupted): Capella may have changed.
        if (result.interrupted or isinstance(result.error, TransportError)
                or client.writes_accepted != writes_before or text == previous):
            return None
        ed.path.write_text(previous, encoding="utf-8")
        ed.original = previous
        return (f"Capella did not accept the change, so {ed.path.name} was restored: nothing was recorded or "
                f"changed. Correct the values and run the command again.")

    env_mod.apply_plan(state, plan, cfg, ctx, shown=True, on_failure=restore)
    return plan, ctx


def _capella_clusters(state: AppState, ed: ConfigEditor, project: str) -> list[dict[str, Any]]:
    """Clusters that exist in Capella for one project of the file (empty when the project is new)."""
    org = ed.doc.get("organizationId")
    client = state.client(org if isinstance(org, str) and not org.startswith("${") else None)
    proj: Any = ed.find_project(project) or {}
    projects = ep.list_projects(client)
    match = [p for p in projects if (p.get("id") == proj.get("id") if proj.get("id") else p.get("name") == proj.get("name"))]
    if len(match) != 1:
        return []
    return ep.list_clusters(client, str(match[0]["id"]))


# ------------------------------------------------------------------ create
@click.command("create", epilog="\b\nExamples:\n  capellactl cluster create nova-dev-02\n"
                                "  capellactl cluster create nova-qa-01 --provider gcp --size medium\n"
                                "  capellactl --auto-approve cluster create nova-ci-01 --size dev")
@click.argument("name")
@click.option("--provider", type=click.Choice(PROVIDERS), help="Cloud provider (asked; default aws).")
@click.option("--region", help="Region (asked; default per provider).")
@click.option("--cidr", help="Cluster network CIDR (asked; default: first free 10.x.y.0/24).")
@click.option("--size", type=click.Choice([*PRESETS, "custom"]), help="Size preset (asked; default small).")
@click.option("--nodes", type=int, help="Nodes (overrides the preset).")
@click.option("--cpu", type=int, help="vCPUs per node (overrides the preset).")
@click.option("--ram", type=int, help="RAM GB per node (overrides the preset).")
@click.option("--disk-type", help="Disk type (default per provider).")
@click.option("--disk-size", type=int, help="Disk GB per node.")
@click.option("--disk-iops", type=int, help="Disk IOPS (AWS).")
@click.option("--services", default=None, help="Comma-separated services (default data,index,query).")
@click.option("--availability", type=click.Choice(["single", "multi"]), help="Availability zones (default multi).")
@click.option("--support-plan", type=click.Choice(SUPPORT_PLANS), help="Support plan (asked; default developer pro).")
@click.option("--support-timezone", type=click.Choice(TIMEZONES), help="Support timezone (default PT).")
@click.option("--description", help="Cluster description.")
@click.option("--project", metavar="NAME", help="Project to deploy into (asked when capella.yaml has several).")
@click.option("--free-tier", is_flag=True, help="Deploy the organization's free single-node cluster "
              "(see 'capellactl cluster options').")
@click.option("--no-apply", is_flag=True, help="Only add the cluster to capella.yaml; deploy later with apply.")
@click.pass_obj
def cluster_create(state: AppState, name: str, project: str | None, free_tier: bool, provider: str | None,
                   region: str | None, cidr: str | None,
                   size: str | None, nodes: int | None, cpu: int | None, ram: int | None, disk_type: str | None,
                   disk_size: int | None, disk_iops: int | None, services: str | None, availability: str | None,
                   support_plan: str | None, support_timezone: str | None, description: str | None,
                   no_apply: bool) -> None:
    """Deploy a new cluster: asks for what it needs, records it in capella.yaml, deploys and waits."""
    ed = open_editor(state)
    interactive = console.is_interactive()
    project = choose_project(ed, project, interactive)
    proj_node = ed.find_project(project)
    assert proj_node is not None
    existing = _capella_clusters(state, ed, project)
    if any(c.get("name") == name for c in existing):
        raise CliExit(ExitCode.BLOCKED, _exists_msg(name))
    keep = _take_undeployed(ed, proj_node, name, project)
    used = [str((c.get("cloudProvider") or {}).get("cidr", "")) for c in existing]
    used += [str((c.get("cloudProvider") or {}).get("cidr", "")) for c in proj_node.get("clusters") or []
             if isinstance(c, dict)]

    sized = any(v is not None for v in (size, nodes, cpu, ram, disk_type, disk_size, disk_iops, services,
                                        availability, support_plan, support_timezone))
    if free_tier and sized:
        raise CliExit(ExitCode.CONFIG_INVALID, "free-tier clusters have a fixed size and plan; remove the size, "
                                               "disk, services, availability and support options")
    if free_tier or (interactive and not sized):
        in_use = free_tier_in_use(_org_client(state, ed), ed)
        if free_tier and in_use:
            raise CliExit(ExitCode.BLOCKED, f"the free tier is already used by {in_use} (one per organization); "
                                            "create a provisioned cluster instead")
        if not free_tier and not in_use:
            out(f"Cluster types: free ({FREE_TIER_NOTE}) or provisioned (you choose size and support plan)")
            free_tier = _ask("Cluster type", "provisioned", ["free", "provisioned"]) == "free"
    if free_tier:
        _create_free(state, ed, proj_node, project, name, provider, region, cidr, description, used, no_apply,
                     interactive, keep)
        return
    answers: dict[str, Any] = {}
    while True:
        provider_ = provider or (_ask("Cloud provider", answers.get("provider", "aws"), PROVIDERS)
                                 if interactive else "aws")
        size_ = size or (_ask("Size", answers.get("size", "small"), [*PRESETS, "custom"]) if interactive else "small")
        preset = dict(PRESETS.get(size_, PRESETS["small"]))
        if size_ == "custom" and interactive:
            preset["nodes"] = nodes or _ask("Nodes", answers.get("nodes", 3), kind=int)
            preset["cpu"] = cpu or _ask("vCPUs per node", answers.get("cpu", 4), kind=int)
            preset["ram"] = ram or _ask("RAM GB per node", answers.get("ram", 16), kind=int)
        region_ = region or (_ask("Region", answers.get("region", REGION_DEFAULT[provider_]))
                             if interactive else REGION_DEFAULT[provider_])
        cidr_ = cidr or (_ask("Network CIDR (must not overlap other clusters)", answers.get("cidr", suggest_cidr(used)))
                         if interactive else suggest_cidr(used))
        plan_ = support_plan or (_ask("Support plan", answers.get("support_plan", "developer pro"), SUPPORT_PLANS)
                                 if interactive else "developer pro")
        answers = {"provider": provider_, "size": size_, "region": region_, "cidr": cidr_, "support_plan": plan_,
                   **{k: preset[k] for k in ("nodes", "cpu", "ram")}}
        disk = dict(DISK_DEFAULT[provider_])
        if disk_type:
            disk = {"type": disk_type, **({} if fixed_size_disk(provider_, disk_type) else {"storage": disk_size or 50})}
        if disk_size is not None:
            disk["storage"] = disk_size
        if disk_iops is not None:
            disk["iops"] = disk_iops
        single = bool(preset.get("single"))
        cluster: dict[str, Any] = {"name": name}
        if description:
            cluster["description"] = description
        if single:
            cluster["configurationType"] = "singleNode"
        cluster["cloudProvider"] = {"type": provider_, "region": region_, "cidr": cidr_}
        cluster["availability"] = {"type": availability or ("single" if single else "multi")}
        cluster["support"] = {"plan": plan_, "timezone": support_timezone or "PT"}
        cluster["serviceGroups"] = [{
            "node": {"compute": {"cpu": cpu or preset["cpu"], "ram": ram or preset["ram"]}, "disk": disk},
            "numOfNodes": nodes or preset["nodes"],
            "services": sorted(s.strip() for s in (services or "data,index,query").split(",") if s.strip()),
        }]
        ed.add_cluster(proj_node, {**cluster, **keep})
        try:
            text = ed.text()
            _validate_candidate(state, ed, text)
            break
        except CliExit as exc:
            ed.remove_cluster(name, proj_node)
            if not interactive or exc.code is not ExitCode.CONFIG_INVALID:
                raise
            # Ask again only for prompted answers; values given as flags are kept, so an error caused
            # by flags alone (e.g. --provider azure --size dev) cannot be fixed by asking.
            bad = set()
            if "cloudProvider.cidr" in exc.message:
                bad |= {"cidr"}
            if "cloudProvider.region" in exc.message:
                bad |= {"region"}
            if any(s in exc.message for s in ("cloudProvider.type", "singleNode", "availability")):
                bad |= {"provider", "size"}
            flags = {"provider": provider, "size": size, "region": region, "cidr": cidr, "support_plan": support_plan}
            if all(flags[k] is not None for k in (bad or flags)):
                raise
            err(exc.message)
            err("Please try again.")
            for k in bad:
                answers.pop(k, None)

    out(f"New cluster {name} in project {project}: {provider_} {region_}, {cluster['serviceGroups'][0]['numOfNodes']} × "
        f"{cluster['serviceGroups'][0]['node']['compute']['cpu']} vCPU/"
        f"{cluster['serviceGroups'][0]['node']['compute']['ram']} GB, network {cidr_}, support {plan_}")
    plan, ctx = change_and_apply(state, ed, f"cluster/{project}/{name}",
                                 f"Add {name} to capella.yaml and deploy it now?", no_apply, text)
    if plan is not None and ctx is not None:
        _record_server_version(ed, name, project, plan, ctx)


def _create_free(state: AppState, ed: ConfigEditor, proj_node: Any, project: str, name: str,
                 provider: str | None, region: str | None, cidr: str | None, description: str | None,
                 used: list[str], no_apply: bool, interactive: bool, keep: dict[str, Any]) -> None:
    from capellactl.config.crossref import FREE_TIER_REGIONS

    provider_ = provider or (_ask("Cloud provider", "aws", PROVIDERS) if interactive else "aws")
    regions = FREE_TIER_REGIONS[provider_]
    region_ = region or (_ask("Region (free-tier regions)", regions[0], regions) if interactive else regions[0])
    cidr_ = cidr or (_ask("Network CIDR (must not overlap other clusters)", suggest_cidr(used))
                     if interactive else suggest_cidr(used))
    cluster: dict[str, Any] = {"name": name}
    if description:
        cluster["description"] = description
    cluster["tier"] = "free"
    cluster["cloudProvider"] = {"type": provider_, "region": region_, "cidr": cidr_}
    ed.add_cluster(proj_node, {**cluster, **keep})
    text = ed.text()
    _validate_candidate(state, ed, text)
    out(f"New free-tier cluster {name} in project {project}: {provider_} {region_}, {FREE_TIER_NOTE}, "
        f"network {cidr_}")
    plan, ctx = change_and_apply(state, ed, f"cluster/{project}/{name}",
                                 f"Add {name} to capella.yaml and deploy it now?", no_apply, text)
    if plan is not None and ctx is not None:
        _record_server_version(ed, name, project, plan, ctx)


# What `cluster create` writes; anything else on an undeployed entry (buckets, credentials, …) is carried over.
CREATE_KEYS = {"id", "name", "description", "tier", "configurationType", "cloudProvider", "availability", "support",
               "serviceGroups", "couchbaseServer", "zones"}


def _take_undeployed(ed: ConfigEditor, proj_node: Any, name: str, project: str) -> dict[str, Any]:
    """A cluster in capella.yaml that never reached Capella (for example a create Capella rejected) is replaced
    by this create, so the user corrects it with the same command instead of editing the file. Returns the
    entry's other settings (buckets, credentials, …) to keep. Called after checking Capella has no such cluster."""
    try:
        found = ed.find_cluster(name, project)
    except LookupError as exc:
        raise CliExit(ExitCode.CONFIG_INVALID, str(exc)) from None
    if found is None:
        return {}
    if "id" in found[1]:  # was deployed once: deleted outside capellactl, so let the user decide
        raise CliExit(ExitCode.BLOCKED, _exists_msg(name))
    keep = {k: v for k, v in found[1].items() if k not in CREATE_KEYS}
    ed.remove_cluster(name, proj_node)
    err(f"{name} is in {ed.path.name} but was never deployed to Capella; replacing it with these settings")
    return keep


def _exists_msg(name: str) -> str:
    return (f"cluster {name} already exists; use 'capellactl cluster update' or 'capellactl cluster scale', "
            f"or 'capellactl sync' to bring it into capella.yaml")


def _record_server_version(ed: ConfigEditor, name: str, project_name: str, plan: Plan, ctx: Any) -> None:
    """After a deploy, record the Couchbase Server version Capella chose, so `sync` has nothing to add."""
    from capellactl.config.editor import to_commented

    action = next((a for a in plan.actions if a.kind == "cluster" and a.key == name
                   and a.parent is not None and a.parent.key == project_name), None)
    project = action.ancestor("project") if action else None
    if action is None or action.status != "done" or not action.id or project is None or not project.id:
        return
    try:
        getter = ep.get_free_cluster if action.data.get("free") else ep.get_cluster
        body, _ = getter(ctx.client, project.id, action.id)
    except Exception:  # noqa: BLE001 - informational; the deploy itself succeeded
        return
    version = (body.get("couchbaseServer") or {}).get("version")
    ed = ConfigEditor(ed.path)  # re-read: apply has just pinned the new ids in the file (CAP-048)
    found = ed.find_cluster(name, project_name)
    cl = found[1] if found else None
    if cl is not None and cl.get("tier") == "free":
        if "id" not in cl:  # free-tier clusters are always recorded with their id
            cl.insert(0, "id", action.id)
            ed.path.write_text(ed.text(), encoding="utf-8")
        return
    if not version or cl is None or "couchbaseServer" in cl:
        return
    pos = list(cl.keys()).index("cloudProvider") + 1 if "cloudProvider" in cl else len(cl)
    cl.insert(pos, "couchbaseServer", to_commented({"version": version}, "couchbaseServer"))
    ed.path.write_text(ed.text(), encoding="utf-8")


# ------------------------------------------------------------------ update
@click.command("update", epilog="\b\nExamples:\n  capellactl cluster update nova-dev-01 --support-plan enterprise\n"
                                "  capellactl cluster update nova-dev-01 --cpu 8 --ram 32\n"
                                "  capellactl cluster update nova-dev-01            (asks what to change)")
@click.argument("name")
@click.option("--description", help="New description.")
@click.option("--support-plan", type=click.Choice(SUPPORT_PLANS))
@click.option("--support-timezone", type=click.Choice(TIMEZONES))
@click.option("--cpu", type=int, help="vCPUs per node for the group.")
@click.option("--ram", type=int, help="RAM GB per node for the group.")
@click.option("--disk-size", type=int, help="Disk GB per node for the group (cannot shrink).")
@click.option("--disk-iops", type=int, help="Disk IOPS for the group (AWS).")
@click.option("--group", metavar="SERVICES", help="Service group to change (default: the group running data).")
@click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name repeats).")
@click.option("--no-apply", is_flag=True, help="Only update capella.yaml; apply later.")
@click.pass_obj
def cluster_update(state: AppState, name: str, project: str | None, description: str | None, support_plan: str | None,
                   support_timezone: str | None, cpu: int | None, ram: int | None, disk_size: int | None,
                   disk_iops: int | None, group: str | None, no_apply: bool) -> None:
    """Change a cluster's description, support plan, CPU/RAM or disk; records it in capella.yaml and applies."""
    ed = open_editor(state)
    proj_node, cl = locate(ed, name, project)
    if cl.get("tier") == "free":
        if any(v is not None for v in (support_plan, support_timezone, cpu, ram, disk_size, disk_iops)):
            raise CliExit(ExitCode.BLOCKED, FREE_FIXED)
        if description is None:
            if not console.is_interactive():
                raise CliExit(ExitCode.CONFIG_INVALID, "nothing to change; free-tier clusters only allow "
                                                       "--description")
            description = _ask("Description", cl.get("description", ""))
        put(cl, "description", description)
        change_and_apply(state, ed, f"cluster/{proj_node.get('name')}/{name}",
                         f"Record this change in capella.yaml and apply it to {name}?", no_apply)
        return
    try:
        g = ed.group(cl, group)
    except LookupError as exc:
        raise CliExit(ExitCode.CONFIG_INVALID, str(exc), topic="scaling") from None
    comp, disk = g["node"]["compute"], g["node"]["disk"]
    support = cl.get("support") or {}
    fixed = fixed_size_disk((cl.get("cloudProvider") or {}).get("type"), disk.get("type"))
    if fixed and (disk_size is not None or disk_iops is not None):
        raise CliExit(ExitCode.CONFIG_INVALID, f"{name} uses Azure disk type {disk.get('type')}, whose size and IOPS "
                                               "are set by the type; --disk-size and --disk-iops apply to Ultra disks "
                                               "only", topic="scaling")
    if not any(v is not None for v in (description, support_plan, support_timezone, cpu, ram, disk_size, disk_iops)):
        if not console.is_interactive():
            raise CliExit(ExitCode.CONFIG_INVALID, "nothing to change; pass for example --support-plan, --cpu, "
                                                   "--ram or --disk-size")
        out(f"Press Enter to keep the current value of {name}.")
        description = _ask("Description", cl.get("description", ""))
        support_plan = _ask("Support plan", str(support.get("plan", "developer pro")).lower(), SUPPORT_PLANS)
        support_timezone = _ask("Support timezone", support.get("timezone", "PT"), TIMEZONES)
        cpu = _ask("vCPUs per node", comp.get("cpu"), kind=int)
        ram = _ask("RAM GB per node", comp.get("ram"), kind=int)
        if "storage" in disk and not fixed:
            disk_size = _ask("Disk GB per node", disk.get("storage"), kind=int)
    if description is not None and description != cl.get("description", ""):
        put(cl, "description", description)
    if support_plan is not None:
        ed.set_path(cl, ["support", "plan"], support_plan)
    if support_timezone is not None:
        ed.set_path(cl, ["support", "timezone"], support_timezone)
    if cpu is not None:
        comp["cpu"] = cpu
    if ram is not None:
        comp["ram"] = ram
    if disk_size is not None:
        disk["storage"] = disk_size
    if disk_iops is not None:
        disk["iops"] = disk_iops
    change_and_apply(state, ed, f"cluster/{proj_node.get('name')}/{name}",
                     f"Record these changes in capella.yaml and apply them to {name}?", no_apply)


# ------------------------------------------------------------------- scale
def scale_in_file(state: AppState, name: str, nodes: int, group: str | None, no_apply: bool,
                  project: str | None = None, skip_capacity_check: bool = False) -> None:
    ed = open_editor(state)
    proj_node, cl = locate(ed, name, project)
    if cl.get("tier") == "free":
        raise CliExit(ExitCode.BLOCKED, FREE_FIXED, topic="scaling")
    try:
        g = ed.group(cl, group)
    except LookupError as exc:
        raise CliExit(ExitCode.CONFIG_INVALID, str(exc), topic="scaling") from None
    g["numOfNodes"] = nodes
    from capellactl.engine.normalize import group_key

    change_and_apply(state, ed, f"cluster/{proj_node.get('name')}/{name}",
                     f"Scale {name} to {nodes} nodes and record it in capella.yaml?",
                     no_apply, noop_message=f"already at {nodes} nodes ({name} {group_key(g)})",
                     skip_capacity_check=skip_capacity_check)


# ----------------------------------------------------------------- options
@click.command("options", epilog="\b\nExamples:\n  capellactl cluster options\n  capellactl -o json cluster options")
@click.pass_obj
def cluster_options(state: AppState) -> None:
    """Show which kinds of cluster you can deploy now (free tier, provisioned) and their choices."""
    from capellactl.config.crossref import FREE_TIER_REGIONS
    from capellactl.output.render import dumps

    path = state.config_path()
    ed = ConfigEditor(path) if path.exists() else None
    client = _org_client(state, ed)
    clusters = org_clusters(client)
    in_use = free_tier_in_use(client, ed)
    regions_in_use = sorted({f"{(c.get('cloudProvider') or {}).get('type')} {(c.get('cloudProvider') or {}).get('region')}"
                             for _, c in clusters if c.get("cloudProvider")})
    if state.json:
        out(dumps({
            "freeTier": {"available": in_use is None, "usedBy": in_use, "regions": FREE_TIER_REGIONS,
                         "includes": FREE_TIER_NOTE, "notIncluded": FREE_TIER_MISSING},
            "provisioned": {"providers": PROVIDERS, "sizes": PRESETS, "supportPlans": SUPPORT_PLANS,
                            "supportTimezones": TIMEZONES, "regionsInUse": regions_in_use,
                            "regionDefaults": REGION_DEFAULT},
        }))
        return
    out(f"Cluster options for organization {client.org_id}")
    out("")
    out("Free tier          " + ("available" if in_use is None else f"not available: already used by {in_use}"))
    out(f"  {FREE_TIER_NOTE}")
    for prov, regs in FREE_TIER_REGIONS.items():
        out(f"  {prov:<6} {', '.join(regs)}")
    out(f"  not included: {FREE_TIER_MISSING}")
    if in_use is None:
        out("  deploy: capellactl cluster create NAME --free-tier [--provider aws --region us-east-2]")
    out("")
    out("Provisioned        available")
    out(f"  providers        {', '.join(PROVIDERS)}")
    sizes = ", ".join(f"{k} ({v['nodes']} × {v['cpu']} vCPU/{v['ram']} GB{', single node' if v.get('single') else ''})"
                      for k, v in PRESETS.items())
    out(f"  sizes            {sizes}, custom")
    out(f"  support plans    {', '.join(SUPPORT_PLANS)} (timezones {', '.join(TIMEZONES)})")
    out("  regions          any region of the provider" + (f"; in use by your clusters: {', '.join(regions_in_use)}"
                                                           if regions_in_use else ""))
    out("                   (Capella's API does not list regions or sizes per organization; one it does not offer")
    out("                    is rejected with Capella's message)")
    out("  deploy: capellactl cluster create NAME [--provider … --size …]")


# -------------------------------------------------------------- step scale


def _limits(index: int, single: bool, lo: int | None, hi: int | None) -> tuple[int, int]:
    if single:
        return 1, 1
    return (lo if lo is not None else (3 if index == 0 else 2)), (hi if hi is not None else (27 if index == 0 else 24))


def step_scale(state: AppState, name: str, step: int, group: str | None, lo: int | None, hi: int | None,
               all_groups: bool, project: str | None, no_apply: bool, skip_capacity_check: bool = False) -> None:
    """`cluster scale NAME --step ±1` (CAP-018): one node more or less per group, within --min/--max."""
    from capellactl.cli.resource_cmds import live_cluster
    from capellactl.engine.clock import get_clock
    from capellactl.engine.normalize import group_key
    from capellactl.engine.waiter import TRANSITIONAL, WaitFailed, WaitTimeout, wait_for_cluster
    from capellactl.output.render import dumps

    client, pid, cl = live_cluster(state, name, project)
    if cl.get("currentState") in TRANSITIONAL:  # AC5: compute the step from the count after the running change
        if state.no_wait:
            raise CliExit(ExitCode.BLOCKED, f"cluster is {cl['currentState']}; try again later", topic="scaling")
        on_state, on_tick = console.wait_progress(f"cluster {name}")
        try:
            wait_for_cluster(client, pid, str(cl["id"]), "ready", state.timeout, get_clock(), on_state, name=name,
                             on_tick=on_tick)
        except (WaitFailed, WaitTimeout) as exc:
            raise CliExit(ExitCode.ERROR, str(exc)) from None
        cl, _ = ep.get_cluster(client, pid, str(cl["id"]))
    live = list(cl.get("serviceGroups") or [])
    single = cl.get("configurationType") == "singleNode"
    if all_groups:
        chosen = list(range(len(live)))
    else:
        key = ",".join(sorted(s.strip() for s in group.split(",") if s.strip())) if group else None
        chosen = [i for i, g in enumerate(live) if (group_key(g) == key if key else "data" in (g.get("services") or []))]
        if len(chosen) != 1:
            raise CliExit(ExitCode.CONFIG_INVALID, f"no single service group {'matches ' + repr(key) if key else 'runs data'}"
                                                   f" (groups: {', '.join(group_key(g) for g in live)}); pass --group",
                          topic="scaling")
    results: list[dict[str, Any]] = []
    for i in chosen:
        g = live[i]
        frm = int(g.get("numOfNodes") or 0)
        low, high = _limits(i, single, lo, hi)
        to = frm + step
        status = "at_limit" if (to > high or to < low) else "scaled"
        results.append({"cluster": name, "group": group_key(g), "from": frm, "to": frm if status == "at_limit" else to,
                        "status": status, "limit": high if step > 0 else low})

    def report(status_override: str | None = None) -> None:
        for r in results:
            if status_override and r["status"] == "scaled":
                r["status"], r["to"] = status_override, r["from"]
        if state.json:
            docs = [{k: v for k, v in r.items() if k != "limit"} for r in results]
            console.emit(dumps(docs[0] if len(docs) == 1 else docs))
            return
        for r in results:
            if r["status"] == "at_limit":
                out(f"{r['group']}: already at {'maximum' if step > 0 else 'minimum'} ({r['limit']})")
            elif r["status"] == "scaled":
                out(f"scaled {r['group']}: {r['from']} → {r['to']}")

    moving = [r for r in results if r["status"] == "scaled"]
    if not moving:  # AC3: at the limit is success with no write
        report()
        return
    ed = open_editor(state)
    proj_node, node = locate(ed, name, project)
    for r in moving:
        try:
            ed.group(node, r["group"])["numOfNodes"] = r["to"]
        except LookupError as exc:
            raise CliExit(ExitCode.CONFIG_INVALID, f"{exc}; run 'capellactl sync' first", topic="scaling") from None
    question = "Apply " + ", ".join(f"{r['group']} {r['from']} → {r['to']}" for r in moving) + \
               f" to {name} and record it in capella.yaml?"
    try:
        with console.muted() if state.json else contextlib.nullcontext():
            plan, _ = change_and_apply(state, ed, f"cluster/{proj_node.get('name')}/{name}", question, no_apply,
                                       skip_capacity_check=skip_capacity_check)
    except CliExit as exc:
        if exc.code == ExitCode.BLOCKED:
            report("blocked")
        raise
    report(None if plan is not None or no_apply else "cancelled")
