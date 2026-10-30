"""Change clusters through commands, never by hand-editing capella.yaml (CAP-038).

Every command: change the file in memory → validate it like `capellactl validate` → show the plan →
ask once → write capella.yaml (keeping a .bak) → apply. A blocked or invalid change writes nothing.
"""

from __future__ import annotations

import contextlib
import difflib
import ipaddress
import os
import re
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
from capellactl.config.presets import is_single_node, load_compute_sizes, load_disk_types, load_presets
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
                          f"'capellactl project create {project}' or add it with 'capellactl sync --project {project}'")
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


class PrefixChoice(click.Choice):  # type: ignore[type-arg]
    """A choice that also takes an unambiguous start of an answer: `multiple` or `m` for `multiple groups`,
    `developer` for `developer pro` (case-insensitive). The full answer is returned."""

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> Any:
        text = str(value).strip().lower()
        exact = [c for c in self.choices if str(c).lower() == text]
        starts = [c for c in self.choices if text and str(c).lower().startswith(text)]
        if exact or len(starts) == 1:
            return (exact or starts)[0]
        return super().convert(value, param, ctx)


def _ask(text: str, default: Any, choices: list[str] | None = None, kind: Any = str) -> Any:
    t = PrefixChoice(choices) if choices else kind
    return console.ask(text, default, type=t, show_choices=bool(choices))


def open_editor(state: AppState) -> ConfigEditor:
    path = state.config_path()
    if not path.exists():
        raise CliExit(ExitCode.CONFIG_INVALID, f"{path} not found; run 'capellactl sync' (or 'capellactl configure') "
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
SERVICES = ["data", "index", "query", "search", "analytics", "eventing"]
DISK_OPTIONS = ("type", "size", "iops", "auto-expansion")
GROUP_SPEC = "SERVICES:NODESxCPU/RAM[:DISK]"
GROUP_LIMITS = "first group 3–27 nodes, other groups 2–24, at most 27 per cluster, one group runs data"
VERSION_SHAPE = re.compile(r"\d+\.\d+(\.\d+)?")


def parse_services(text: str, where: str) -> list[str]:
    """Sorted services of a group; an unknown name exits 3 with the closest match (CAP-051 AC2)."""
    names = [s.strip() for s in text.split(",") if s.strip()]
    if not names:
        raise CliExit(ExitCode.CONFIG_INVALID, f"{where}: no services (for example data,index,query)", topic="scaling")
    for n in names:
        if n not in SERVICES:
            close = difflib.get_close_matches(n, SERVICES, n=1)
            hint = f"; did you mean {close[0]}?" if close else f"; use {', '.join(SERVICES)}"
            raise CliExit(ExitCode.CONFIG_INVALID, f"{where}: unknown service '{n}'{hint}", topic="scaling")
    return sorted(set(names))


def make_disk(provider: str, disk_type: str | None = None, size: int | None = None, iops: int | None = None,
              auto_expansion: bool | None = None) -> dict[str, Any]:
    """A group's disk: the provider default, with the given values on top. Without IOPS, gp3, io2 and Ultra disks get
    Capella's recommended IOPS for their size (CAP-060 AC3)."""
    from capellactl.config.presets import default_iops, disk_facts

    disk = dict(DISK_DEFAULT[provider])
    if disk_type:
        disk = {"type": disk_type}
        if not fixed_size_disk(provider, disk_type):
            facts = disk_facts(provider, disk_type) or {}
            disk["storage"] = int((facts.get("sizes") or facts.get("size") or [50])[0])  # the smallest size allowed
    if size is not None:
        disk["storage"] = size
    if iops is not None:
        disk["iops"] = iops
    elif "storage" in disk:
        recommended = default_iops(provider, str(disk["type"]), int(disk["storage"]))
        if recommended is not None:
            disk["iops"] = recommended
    if auto_expansion is not None:
        disk["autoExpansion"] = auto_expansion
    return disk


def parse_group_spec(text: str, provider: str, disk_defaults: dict[str, Any]) -> dict[str, Any]:
    """`--group SERVICES:NODESxCPU/RAM[:DISK]` → one service group (CAP-051). Errors name the part that is wrong."""
    where = f"--group {text}"
    parts = text.split(":")
    if len(parts) not in (2, 3):
        raise CliExit(ExitCode.CONFIG_INVALID, f"{where}: expected {GROUP_SPEC}, e.g. data:3x8/32", topic="scaling")
    services = parse_services(parts[0], where)
    m = re.fullmatch(r"\s*(\d+)\s*x\s*(\d+)\s*/\s*(\d+)\s*", parts[1])
    if not m:
        raise CliExit(ExitCode.CONFIG_INVALID, f"{where}: expected NODESxCPU/RAM, e.g. 3x8/32 (got '{parts[1]}')",
                      topic="scaling")
    disk = dict(disk_defaults)
    for item in (parts[2].split(",") if len(parts) == 3 else []):
        key, sep, value = (x.strip() for x in item.partition("="))
        if not sep or key not in DISK_OPTIONS:
            raise CliExit(ExitCode.CONFIG_INVALID, f"{where}: unknown disk option '{key}'; use type, size, iops, "
                                                   "auto-expansion", topic="scaling")
        if key in ("size", "iops"):
            if not value.isdigit():
                raise CliExit(ExitCode.CONFIG_INVALID, f"{where}: {key} must be a whole number (got '{value}')",
                              topic="scaling")
            disk[key] = int(value)
        elif key == "auto-expansion":
            if value.lower() not in ("true", "false"):
                raise CliExit(ExitCode.CONFIG_INVALID, f"{where}: auto-expansion is true or false (got '{value}')",
                              topic="scaling")
            disk[key] = value.lower() == "true"
        elif not value:
            raise CliExit(ExitCode.CONFIG_INVALID, f"{where}: type needs a value, e.g. type=io2", topic="scaling")
        else:
            disk[key] = value
    return {"node": {"compute": {"cpu": int(m.group(2)), "ram": int(m.group(3))},
                     "disk": make_disk(provider, disk.get("type"), disk.get("size"), disk.get("iops"),
                                       disk.get("auto-expansion"))},
            "numOfNodes": int(m.group(1)), "services": services}


def data_first(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The first group that runs data goes first, so the 3–27 node rule of the first group applies to it."""
    first = next((g for g in groups if "data" in g["services"]), None)
    return groups if first is None or first is groups[0] else [first, *[g for g in groups if g is not first]]


def size_warnings(provider: str, groups: list[dict[str, Any]], single: bool) -> list[str]:
    """Plan notes for sizes Capella's documentation does not list (CAP-051 AC9); Capella still has the last word."""
    from capellactl.config.presets import known_size
    from capellactl.engine.normalize import group_key

    lines = []
    for g in groups:
        comp = g["node"]["compute"]
        if not known_size(provider, int(comp["cpu"]), int(comp["ram"]), single):
            lines.append(f"! serviceGroups[{group_key(g)}]: {comp['cpu']} vCPU/{comp['ram']} GB is not a known "
                         f"{provider} size; Capella may reject it (see 'capellactl cluster options')")
    return lines


def _ask_node_size(provider: str, default: tuple[int, int]) -> tuple[int, int]:
    """Choose a node size from the known sizes (CAP-051 AC9); 'other' types vCPUs and RAM."""
    from capellactl.config.presets import load_compute_sizes

    sizes: list[tuple[int, int]] = load_compute_sizes().get(provider, {}).get("sizes", [])
    out("  Node size (vCPU / RAM GB):")
    for row in range(0, len(sizes), 6):
        out("    " + "  ".join(f"{i + 1:>2}) {c}/{r}" for i, (c, r) in enumerate(sizes[row:row + 6], row)))
    out(f"    {len(sizes) + 1:>2}) other")
    pick = int(_ask("  Choose", sizes.index(default) + 1 if default in sizes else 1, kind=click.IntRange(1, len(sizes) + 1)))
    if pick <= len(sizes):
        return sizes[pick - 1]
    return int(_ask("  vCPUs per node", default[0], kind=int)), int(_ask("  RAM GB per node", default[1], kind=int))


def disk_rows(provider: str | None = None) -> list[tuple[str, ...]]:
    """`cluster disk-types` rows: PROVIDER, TYPE, SIZE (GB), IOPS, FOR (CAP-060 AC1)."""
    from capellactl.config.presets import disk_iops_text, disk_size_text, load_disk_types

    rows: list[tuple[str, ...]] = [("PROVIDER", "TYPE", "SIZE (GB)", "IOPS", "FOR")]
    for prov, types in load_disk_types().items():
        if provider in (None, prov):
            rows += [(prov, t, disk_size_text(f), disk_iops_text(f), str(f.get("for", ""))) for t, f in types.items()]
    return rows


def _ask_disk(provider: str, current: dict[str, Any] | None = None) -> dict[str, Any]:
    """Choose a group's disk (CAP-060 AC2): the provider's types with what they mean, then only what the type lets
    you set: size (with its range) and IOPS (default: Capella's recommendation for the size)."""
    from capellactl.cli.resource_cmds import _list_table
    from capellactl.config.presets import default_iops, disk_facts, iops_range, load_disk_types

    types = list(load_disk_types().get(provider, {}))
    if not types:
        return make_disk(provider)
    current = current or make_disk(provider)
    out("  Disk type:")
    for line in _list_table(disk_rows(provider)).splitlines():
        out("    " + line)
    default = types.index(current["type"]) + 1 if current.get("type") in types else 1
    disk_type = types[int(_ask("  Choose", default, kind=click.IntRange(1, len(types)))) - 1]
    facts = disk_facts(provider, disk_type) or {}
    if "fixedSize" in facts:
        out(f"    {disk_type}: {facts['fixedSize']} GB, {facts['fixedIops']} IOPS (set by the type)")
        return make_disk(provider, disk_type)
    first = make_disk(provider, disk_type)
    same = current.get("type") == disk_type
    start = int(current.get("storage", first["storage"])) if same else int(first["storage"])
    if "sizes" in facts:
        sizes = [int(s) for s in facts["sizes"]]
        size = int(console.ask(f"  Disk GB per node ({', '.join(map(str, sizes[:5]))}, … {sizes[-1]})", start,
                               type=click.Choice([str(s) for s in sizes]), show_choices=False))
    else:
        lo, *hi = facts.get("size") or [50]
        size = int(_ask(f"  Disk GB per node ({lo}–{hi[0]})" if hi else f"  Disk GB per node (at least {lo})", start,
                        kind=click.IntRange(lo, hi[0] if hi else None)))
    if "perGb" in facts:
        per = int(facts["perGb"]) // 2
        out(f"    {disk_type} {size} GB: up to {per * size} read and {per * size} write IOPS")
        return make_disk(provider, disk_type, size)
    rng = iops_range(provider, disk_type, size)
    recommended = default_iops(provider, disk_type, size) or (rng[0] if rng else 3000)
    keep = int(current["iops"]) if same and current.get("iops") and int(current["iops"]) >= recommended else None
    label = f"  IOPS ({rng[0]}–{rng[1]}; recommended {recommended} for {size} GB)" if rng else "  IOPS"
    iops = int(_ask(label, keep or recommended, kind=click.IntRange(*rng) if rng else int))
    return make_disk(provider, disk_type, size, iops)


def _ask_groups(provider: str, disk_defaults: dict[str, Any]) -> list[dict[str, Any]]:
    """Interactive multi-group create (CAP-051 AC6): each answer is checked as it is given."""
    groups: list[dict[str, Any]] = []
    while True:
        total = sum(g["numOfNodes"] for g in groups)
        out(f"Service group {len(groups) + 1}" + (f"  (nodes so far: {total} of 27)" if groups else ""))
        used = {",".join(g["services"]) for g in groups}
        # The default is the services no group runs yet (every service for the first group).
        unused = [s for s in SERVICES if not any(s in g["services"] for g in groups)]
        default = ",".join(unused) or None
        while True:
            try:
                services = parse_services(_ask("  Services", default), "services")
            except CliExit as exc:
                err(exc.message)
                continue
            if ",".join(services) in used:
                err(f"a group already runs {','.join(services)}; each group needs a different set of services")
                continue
            break
        is_first_data = "data" in services and not any("data" in g["services"] for g in groups)
        low, high = (3, 27) if is_first_data else (2, 24)
        while True:
            nodes = _ask(f"  Nodes ({low}–{high})", low, kind=int)
            if not low <= nodes <= high:
                err(f"this group needs {low}–{high} nodes")
            elif total + nodes > 27:
                err(f"a cluster can have at most 27 nodes; {27 - total} left")
            else:
                break
        cpu, ram = _ask_node_size(provider, (4, 16))
        disk = dict(disk_defaults)
        if disk.get("type") is None and disk.get("size") is None and disk.get("iops") is None:
            chosen = _ask_disk(provider)
        else:  # disk flags were given: they apply to every group, nothing to ask
            chosen = make_disk(provider, disk.get("type"), disk.get("size"), disk.get("iops"))
        if disk.get("auto-expansion") is not None:
            chosen["autoExpansion"] = disk["auto-expansion"]
        groups.append({"node": {"compute": {"cpu": cpu, "ram": ram}, "disk": chosen},
                       "numOfNodes": nodes, "services": services})
        if sum(g["numOfNodes"] for g in groups) > 25 or not console.ask_yes_no("Add another service group?", False):
            return groups


class _CreateCommand(click.Command):
    """`cluster create --help` lists the advanced options (CAP-053) under their own heading."""

    ADVANCED = {"single_node", "server_version", "zone", "cmek_id", "private_dns", "disk_auto_expansion"}

    def format_options(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        rows: list[tuple[str, str]] = []
        advanced: list[tuple[str, str]] = []
        for param in self.get_params(ctx):
            record = param.get_help_record(ctx)
            if record:
                (advanced if param.name in self.ADVANCED else rows).append(record)
        with formatter.section("Options"):
            formatter.write_dl(rows)
        with formatter.section("Advanced options (not asked; set only on the command line)"):
            formatter.write_dl(advanced)


def _groups_line(groups: list[dict[str, Any]]) -> str:
    return " · ".join(f"{','.join(g['services'])} {g['numOfNodes']} × {g['node']['compute']['cpu']}/"
                      f"{g['node']['compute']['ram']}" for g in groups)


@click.command("create", cls=_CreateCommand, epilog="\b\nExamples:\n  capellactl cluster create nova-dev-02\n"
                                "  capellactl cluster create nova-qa-01 --provider gcp --size medium\n"
                                "  capellactl --auto-approve cluster create nova-ci-01 --size dev\n"
                                "  capellactl cluster create nova-prod-01 --group data:3x8/32 --group index,query:2x8/32 "
                                "--group search:2x4/16\n"
                                "  capellactl cluster create nova-prod-02 --group data:3x8/32:size=100 "
                                "--group analytics:2x16/64:size=200,iops=5000\n"
                                "  capellactl cluster create nova-dev-03 --single-node --cpu 8 --ram 32\n"
                                "\b\n"
                                f"--group {GROUP_SPEC} (repeatable; one per service group):\n"
                                "  SERVICES  data, index, query, search, analytics, eventing (comma-separated)\n"
                                "  NODESxCPU/RAM  nodes, vCPUs and GB of RAM per node, e.g. 3x8/32\n"
                                "  DISK      type=, size= (GB), iops=, auto-expansion= (azure)\n"
                                "Sizes Capella offers: capellactl cluster options. To copy the layout of an existing "
                                "cluster: capellactl cluster clone SOURCE NEW_NAME --region REGION --no-data-model")
@click.argument("name")
@click.option("--provider", type=click.Choice(PROVIDERS), help="Cloud provider (asked; default aws).")
@click.option("--region", help="Region (asked; default per provider).")
@click.option("--cidr", help="Cluster network CIDR (asked; default: first free 10.x.y.0/24).")
@click.option("--size", type=click.Choice([*PRESETS, "custom"]), help="Size preset (asked; default small).")
@click.option("--nodes", type=int, help="Nodes (overrides the preset).")
@click.option("--cpu", type=int, help="vCPUs per node (overrides the preset).")
@click.option("--ram", type=int, help="RAM GB per node (overrides the preset).")
@click.option("--group", "groups", multiple=True, metavar="SPEC",
              help=f"A service group as {GROUP_SPEC}, e.g. data:3x8/32 (repeatable; replaces --nodes, --cpu, --ram, "
                   "--services and --size).")
@click.option("--disk-type", help="Disk type (default per provider; see 'capellactl cluster disk-types').")
@click.option("--disk-size", type=int, help="Disk GB per node.")
@click.option("--disk-iops", type=int, help="Disk IOPS (AWS gp3/io2, Azure Ultra; default: Capella's recommendation "
                                            "for the size).")
@click.option("--services", default=None, help="Comma-separated services (default data,index,query).")
@click.option("--availability", type=click.Choice(["single", "multi"]), help="Availability zones (default multi).")
@click.option("--support-plan", type=click.Choice(SUPPORT_PLANS), help="Support plan (asked; default developer pro).")
@click.option("--support-timezone", type=click.Choice(TIMEZONES), help="Support timezone (default PT).")
@click.option("--description", help="Cluster description.")
@click.option("--project", metavar="NAME", help="Project to deploy into (asked when capella.yaml has several).")
@click.option("--free-tier", is_flag=True, help="Deploy the organization's free single-node cluster "
              "(see 'capellactl cluster options').")
@click.option("--no-apply", is_flag=True, help="Only add the cluster to capella.yaml; deploy later with apply.")
@click.option("--single-node", is_flag=True, help="One node (development); takes --cpu/--ram (default 4/16).")
@click.option("--server-version", metavar="VERSION", help="Couchbase Server version, e.g. 8.0 (default: Capella's).")
@click.option("--zone", metavar="ZONE", help="Availability zone (single-AZ clusters only).")
@click.option("--cmek-id", metavar="ID", help="ID of an existing customer-managed encryption key.")
@click.option("--private-dns", is_flag=True, help="Enable private DNS resolution.")
@click.option("--disk-auto-expansion/--no-disk-auto-expansion", default=None,
              help="Azure: let disk storage expand automatically.")
@click.pass_obj
def cluster_create(state: AppState, name: str, project: str | None, free_tier: bool, provider: str | None,
                   region: str | None, cidr: str | None,
                   size: str | None, nodes: int | None, cpu: int | None, ram: int | None, groups: tuple[str, ...],
                   disk_type: str | None, disk_size: int | None, disk_iops: int | None, services: str | None,
                   availability: str | None, support_plan: str | None, support_timezone: str | None,
                   description: str | None, no_apply: bool, single_node: bool, server_version: str | None,
                   zone: str | None, cmek_id: str | None, private_dns: bool, disk_auto_expansion: bool | None) -> None:
    """Deploy a new cluster: asks for what it needs, records it in capella.yaml, deploys and waits."""
    _check_create_options(groups, single_node, size, nodes, cpu, ram, services, availability, server_version, cmek_id)
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

    advanced = single_node or private_dns or any(v is not None for v in (server_version, zone, cmek_id,
                                                                         disk_auto_expansion))
    sized = bool(groups) or advanced or any(v is not None for v in (
        size, nodes, cpu, ram, disk_type, disk_size, disk_iops, services, availability, support_plan, support_timezone))
    if free_tier and sized:
        raise CliExit(ExitCode.CONFIG_INVALID, "free-tier clusters have a fixed size and plan; remove the size, "
                                               "disk, services, availability, support and advanced options")
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
    disk_defaults = {"type": disk_type, "size": disk_size, "iops": disk_iops, "auto-expansion": disk_auto_expansion}
    answers: dict[str, Any] = {}
    while True:
        provider_ = provider or (_ask("Cloud provider", answers.get("provider", "aws"), PROVIDERS)
                                 if interactive else "aws")
        layout: list[dict[str, Any]] | None = None
        asked_disk: dict[str, Any] | None = None
        if groups:
            layout = data_first([parse_group_spec(g, provider_, disk_defaults) for g in groups])
            size_ = "custom"
        elif single_node:
            size_ = "custom"
        else:
            size_ = size or (_ask("Size", answers.get("size", "small"), [*PRESETS, "custom"])
                             if interactive else "small")
        preset = dict(PRESETS.get(size_, PRESETS["small"]))
        if single_node:
            preset = {"nodes": 1, "cpu": 4, "ram": 16, "single": True}
        elif size_ == "custom" and interactive and layout is None:
            if "groups" in answers:
                layout = answers["groups"]
            elif _ask("Service layout", "one group", ["one group", "multiple groups"]) == "multiple groups":
                layout = data_first(_ask_groups(provider_, disk_defaults))
            else:
                preset["nodes"] = nodes or _ask("Nodes", answers.get("nodes", 3), kind=int)
                preset["cpu"] = cpu or _ask("vCPUs per node", answers.get("cpu", 4), kind=int)
                preset["ram"] = ram or _ask("RAM GB per node", answers.get("ram", 16), kind=int)
                if disk_type is None and disk_size is None and disk_iops is None:
                    asked_disk = answers.get("disk") or _ask_disk(provider_)
        region_ = region or (_ask("Region", answers.get("region", REGION_DEFAULT[provider_]))
                             if interactive else REGION_DEFAULT[provider_])
        cidr_ = cidr or (_ask("Network CIDR (must not overlap other clusters)", answers.get("cidr", suggest_cidr(used)))
                         if interactive else suggest_cidr(used))
        plan_ = support_plan or (_ask("Support plan", answers.get("support_plan", "developer pro"), SUPPORT_PLANS)
                                 if interactive else "developer pro")
        answers = {"provider": provider_, "size": size_, "region": region_, "cidr": cidr_, "support_plan": plan_,
                   **{k: preset[k] for k in ("nodes", "cpu", "ram")}, **({"disk": asked_disk} if asked_disk else {})}
        if layout is not None and not groups:
            answers["groups"] = layout
        single = bool(preset.get("single"))
        if layout is None:
            disk_ = dict(asked_disk) if asked_disk else make_disk(provider_, disk_type, disk_size, disk_iops)
            if disk_auto_expansion is not None:
                disk_["autoExpansion"] = disk_auto_expansion
            layout = [{
                "node": {"compute": {"cpu": cpu or preset["cpu"], "ram": ram or preset["ram"]}, "disk": disk_},
                "numOfNodes": nodes or preset["nodes"],
                "services": sorted(s.strip() for s in (services or "data,index,query").split(",") if s.strip()),
            }]
        cluster: dict[str, Any] = {"name": name}
        if description:
            cluster["description"] = description
        if single:
            cluster["configurationType"] = "singleNode"
        cluster["cloudProvider"] = {"type": provider_, "region": region_, "cidr": cidr_}
        if server_version:
            cluster["couchbaseServer"] = {"version": server_version}
        cluster["availability"] = {"type": availability or ("single" if single else "multi")}
        cluster["support"] = {"plan": plan_, "timezone": support_timezone or "PT"}
        cluster["serviceGroups"] = layout
        if zone:
            cluster["zones"] = [zone]
        if cmek_id:
            cluster["cmekId"] = cmek_id
        if private_dns:
            cluster["enablePrivateDNSResolution"] = True
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
            if "serviceGroups" in exc.message and not groups:
                bad |= {"groups"}
            flags = {"provider": provider, "size": size, "region": region, "cidr": cidr, "support_plan": support_plan,
                     "groups": groups or None}
            if all(flags[k] is not None for k in (bad or flags)):
                raise
            err(exc.message)
            err("Please try again.")
            for k in bad | ({"disk"} if "provider" in bad else set()):  # a disk belongs to its provider
                answers.pop(k, None)

    sg = cluster["serviceGroups"]
    if len(sg) > 1:
        sizing = f"{len(sg)} groups · {sum(g['numOfNodes'] for g in sg)} nodes ({_groups_line(sg)})"
    else:
        sizing = f"{sg[0]['numOfNodes']} × {sg[0]['node']['compute']['cpu']} vCPU/{sg[0]['node']['compute']['ram']} GB"
    out(f"New cluster {name} in project {project}: {provider_} {region_}, {sizing}, network {cidr_}, support {plan_}")
    plan, ctx = change_and_apply(state, ed, f"cluster/{project}/{name}",
                                 f"Add {name} to capella.yaml and deploy it now?", no_apply, text,
                                 after_plan=size_warnings(provider_, sg, single))
    if plan is not None and ctx is not None:
        _record_server_version(ed, name, project, plan, ctx)


def _check_create_options(groups: tuple[str, ...], single_node: bool, size: str | None, nodes: int | None,
                          cpu: int | None, ram: int | None, services: str | None, availability: str | None,
                          server_version: str | None, cmek_id: str | None) -> None:
    """Combinations refused before anything is read or written (CAP-051 AC3, CAP-053 AC2–AC3)."""
    if groups:
        given = [f for f, v in (("--nodes", nodes), ("--cpu", cpu), ("--ram", ram), ("--services", services),
                                ("--size", size)) if v is not None]
        if given:
            raise CliExit(ExitCode.CONFIG_INVALID, f"--group sets nodes, size and services per group; remove "
                                                   f"{', '.join(given)}", topic="scaling")
    if single_node:
        if size is not None:
            raise CliExit(ExitCode.CONFIG_INVALID, "--single-node sets the size; remove --size", topic="scaling")
        if nodes not in (None, 1):
            raise CliExit(ExitCode.CONFIG_INVALID, "singleNode clusters have exactly 1 node; remove --nodes",
                          topic="scaling")
        if availability == "multi":
            raise CliExit(ExitCode.CONFIG_INVALID, "singleNode clusters must use availability: single",
                          topic="scaling")
        if len(groups) > 1:
            raise CliExit(ExitCode.CONFIG_INVALID, "singleNode clusters have exactly one service group",
                          topic="scaling")
    if server_version is not None and not VERSION_SHAPE.fullmatch(server_version):
        raise CliExit(ExitCode.CONFIG_INVALID, f"--server-version takes a version like 8.0 or 7.6.4 (got "
                                               f"'{server_version}')")
    if cmek_id is not None and not cmek_id.strip():
        raise CliExit(ExitCode.CONFIG_INVALID, "--cmek-id needs the ID of an existing encryption key")


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
                                "  capellactl cluster update nova-dev-01            (asks what to change)\n"
                                "  capellactl cluster update nova-dev-01 --group data --disk-type io2 --disk-iops 20000\n"
                                "  capellactl cluster update nova-az-01 --disk-auto-expansion  (azure)\n"
                                "Disk types and what they mean: capellactl cluster disk-types")
@click.argument("name")
@click.option("--description", help="New description.")
@click.option("--support-plan", type=click.Choice(SUPPORT_PLANS))
@click.option("--support-timezone", type=click.Choice(TIMEZONES))
@click.option("--cpu", type=int, help="vCPUs per node for the group.")
@click.option("--ram", type=int, help="RAM GB per node for the group.")
@click.option("--disk-type", help="Disk type for the group (see 'capellactl cluster disk-types').")
@click.option("--disk-size", type=int, help="Disk GB per node for the group (cannot shrink).")
@click.option("--disk-iops", type=int, help="Disk IOPS for the group (AWS gp3/io2, Azure Ultra).")
@click.option("--disk-auto-expansion/--no-disk-auto-expansion", default=None,
              help="Azure: let the group's disk storage expand automatically.")
@click.option("--group", metavar="SERVICES", help="Service group to change (default: the group running data).")
@click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name repeats).")
@click.option("--no-apply", is_flag=True, help="Only update capella.yaml; apply later.")
@click.pass_obj
def cluster_update(state: AppState, name: str, project: str | None, description: str | None, support_plan: str | None,
                   support_timezone: str | None, cpu: int | None, ram: int | None, disk_type: str | None,
                   disk_size: int | None, disk_iops: int | None, disk_auto_expansion: bool | None, group: str | None,
                   no_apply: bool) -> None:
    """Change a cluster's description, support plan, CPU/RAM or disk; records it in capella.yaml and applies."""
    ed = open_editor(state)
    proj_node, cl = locate(ed, name, project)
    if cl.get("tier") == "free":
        if any(v is not None for v in (support_plan, support_timezone, cpu, ram, disk_type, disk_size, disk_iops,
                                       disk_auto_expansion)):
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
    provider = str((cl.get("cloudProvider") or {}).get("type"))
    after_plan: list[str] = []
    if disk_type is not None and disk_type != disk.get("type"):
        after_plan = _change_disk_type(provider, disk, disk_type, disk_size, disk_iops)
    fixed = fixed_size_disk(provider, disk.get("type"))
    if fixed and (disk_size is not None or disk_iops is not None):
        raise CliExit(ExitCode.CONFIG_INVALID, f"{name} uses Azure disk type {disk.get('type')}, whose size and IOPS "
                                               "are set by the type; --disk-size and --disk-iops apply to Ultra disks "
                                               "only", topic="scaling")
    if disk_auto_expansion is not None and provider != "azure":
        raise CliExit(ExitCode.CONFIG_INVALID, "auto-expansion is for azure disks only", topic="scaling")
    if disk_iops is not None and provider == "gcp":
        raise CliExit(ExitCode.CONFIG_INVALID, "Google Cloud pd-ssd disks get their IOPS from their size (60 per GB); "
                                               "use --disk-size to make the disk faster (capellactl cluster disk-types)",
                      topic="scaling")
    if not any(v is not None for v in (description, support_plan, support_timezone, cpu, ram, disk_type, disk_size,
                                       disk_iops, disk_auto_expansion)):
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
    if disk_auto_expansion is not None:
        disk["autoExpansion"] = disk_auto_expansion
    change_and_apply(state, ed, f"cluster/{proj_node.get('name')}/{name}",
                     f"Record these changes in capella.yaml and apply them to {name}?", no_apply,
                     after_plan=after_plan)


def _change_disk_type(provider: str, disk: Any, new_type: str, size: int | None, iops: int | None) -> list[str]:
    """Give a group's disk a new type in place (CAP-060 AC5): the size is kept where the new type allows it, IOPS
    become the recommendation for the size unless given. Returns the plan lines that say what the type means."""
    from capellactl.config.presets import disk_facts, disk_iops_text

    facts = disk_facts(provider, new_type)
    if facts is None:  # validation names the allowed types
        disk["type"] = new_type
        return []
    keep = None if fixed_size_disk(provider, new_type) else (size if size is not None else disk.get("storage"))
    allowed = facts.get("sizes")
    if keep is not None and allowed and int(keep) not in allowed:
        keep = None
    fresh = make_disk(provider, new_type, int(keep) if keep is not None else None, iops)
    for k in ("storage", "iops"):
        disk.pop(k, None)
    disk.update(fresh)
    lines = [f"  disk type {new_type}: {facts.get('for')} (IOPS {disk_iops_text(facts)})"]
    if provider == "aws":
        lines.append("  AWS changes a disk in place at most once every 6 hours; otherwise Capella replaces and "
                     "rebalances the nodes")
    else:
        lines.append("  Capella replaces and rebalances the group's nodes to change its disk type")
    return lines


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
    versions_in_use = sorted({str((c.get("couchbaseServer") or {}).get("version")) for _, c in clusters
                              if (c.get("couchbaseServer") or {}).get("version")})
    known = {prov: [f"{cpu}/{ram}" for cpu, ram in kinds.get("sizes", [])] for prov, kinds in load_compute_sizes().items()}
    disks = {prov: list(types) for prov, types in load_disk_types().items()}
    if state.json:
        out(dumps({
            "freeTier": {"available": in_use is None, "usedBy": in_use, "regions": FREE_TIER_REGIONS,
                         "includes": FREE_TIER_NOTE, "notIncluded": FREE_TIER_MISSING},
            "provisioned": {"providers": PROVIDERS, "sizes": PRESETS, "supportPlans": SUPPORT_PLANS,
                            "supportTimezones": TIMEZONES, "regionsInUse": regions_in_use,
                            "regionDefaults": REGION_DEFAULT, "services": SERVICES, "groupLimits": GROUP_LIMITS,
                            "nodeSizes": known, "diskTypes": disks, "serverVersionsInUse": versions_in_use},
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
    out(f"  services         {', '.join(SERVICES)}")
    out(f"  service groups   {GROUP_LIMITS}")
    out("  node sizes       vCPU/RAM GB (from Capella's documentation; config/compute.yaml)")
    for prov, sizes_ in known.items():
        out(f"    {prov:<6} {', '.join(sizes_)}")
    out("  disk types       " + " · ".join(f"{prov} {', '.join(types)}" for prov, types in disks.items()))
    out("                   (size, speed and use of each: capellactl cluster disk-types)")
    if versions_in_use:
        out(f"  server versions  in use by your clusters: {', '.join(versions_in_use)}")
    out("  regions          any region of the provider" + (f"; in use by your clusters: {', '.join(regions_in_use)}"
                                                           if regions_in_use else ""))
    out("                   (Capella's API does not list regions or sizes per organization; one it does not offer")
    out("                    is rejected with Capella's message)")
    out("  deploy: capellactl cluster create NAME [--provider … --size …]")
    out("          capellactl cluster create NAME --group data:3x8/32 --group index,query:2x8/32 …  (several groups)")


@click.command("disk-types", epilog="\b\nExamples:\n  capellactl cluster disk-types\n"
                                    "  capellactl cluster disk-types --provider aws\n"
                                    "  capellactl -o json cluster disk-types --provider azure")
@click.option("--provider", type=click.Choice(PROVIDERS), help="Only this cloud provider's disk types.")
@click.pass_obj
def cluster_disk_types(state: AppState, provider: str | None) -> None:
    """List the disk types you can choose per service group: size range, speed (IOPS) and what each is for."""
    from capellactl.cli.resource_cmds import _list_table
    from capellactl.output.render import dumps

    if state.json:
        out(dumps({p: types for p, types in load_disk_types().items() if provider in (None, p)}))
        return
    out(_list_table(disk_rows(provider)))
    out("Without --disk-iops, gp3, io2 and Ultra disks get Capella's recommended IOPS for their size; a higher value "
        "is allowed.")
    out("Changing a running cluster's disk: AWS changes it in place at most once every 6 hours; otherwise, and on "
        "Azure, Capella replaces and rebalances the nodes.")


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
