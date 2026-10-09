"""capellactl init: write a valid, commented capella.yaml from a few answers (CAP-035).

Read-only towards Capella: with an API key it lists organizations and projects (GET only); without one the
organization ID is typed. Every answer is checked with the same validation as `capellactl validate`
(CAP-002) on the document built so far; an invalid answer shows that message and is asked again. Nothing is
written until the whole file validates. The API key and passwords are never written: credentials get
`password: ${ENV_VAR}`.

The "Existing Capella project" path hands over to `capellactl import` (CAP-036) with the same output file.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click

from capellactl.api import endpoints as ep
from capellactl.api.client import CapellaClient
from capellactl.cli import console
from capellactl.cli.cluster_ops import DISK_DEFAULT, PROVIDERS, REGION_DEFAULT, SUPPORT_PLANS, suggest_cidr
from capellactl.cli.console import err, note, out
from capellactl.cli.env import pass_state
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.state import AppState
from capellactl.config.crossref import normalize_cidr
from capellactl.config.loader import API_VERSION, ConfigError, ConfigIssue, load_config
from capellactl.config.presets import is_single_node, load_presets
from capellactl.engine.clock import get_clock

OFFICE_HOURS = "08:00-18:00"
TIMEZONE = "US/Pacific"
ACCESS = {"read": ["data_reader"], "read-write": ["data_reader", "data_writer"]}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PLACEHOLDER = "Capellactl-Init-Placeholder-1!"  # stands in for password variables while validating (meets Capella rules)

HEADER = """\
# capella.yaml: your Capella environment, written by `capellactl init`__ORG__.
# Next: `capellactl validate`, `capellactl plan`, `capellactl apply`. Change it later with capellactl commands
# (`cluster update|scale|protect`, `bucket …`, `cidr …`); `capellactl help config <field>` explains every field.
# No secrets are written here: the API key stays in your keychain or CAPELLA_API_KEY, and passwords are
# ${ENV_VAR} references read when you run apply.

"""
COMMENTS = {
    "project": "The Capella project (capellactl help config project).",
    "clusters": "Clusters of the project (capellactl help config clusters).",
    "configurationType": "singleNode: one node for development; it cannot be scaled out later.",
    "cloudProvider": "Immutable after creation: provider, region and network (capellactl help config "
                     "clusters.cloudProvider).",
    "support": "Updatable in place (capellactl help config clusters.support).",
    "serviceGroups": "Nodes and services; change with `capellactl cluster scale|update` (capellactl help config "
                     "clusters.serviceGroups).",
    "deletionProtection": "true blocks deleting the cluster and its buckets (capellactl help config "
                          "clusters.deletionProtection).",
    "hibernation": "Capella turns the cluster off outside these on-windows (capellactl help config "
                   "clusters.hibernation).",
    "allowAnyIp": "Confirms that 0.0.0.0/0 (any IP address) is intended.",
    "allowedCidrs": "IP ranges allowed to connect (capellactl help config clusters.allowedCidrs).",
    "buckets": "Buckets, scopes and collections (capellactl help config clusters.buckets).",
    "databaseCredentials": "Passwords come from the environment variables named here (capellactl help config "
                           "clusters.databaseCredentials).",
}


@dataclass
class Answers:
    org_id: str = ""
    org_name: str | None = None
    project: str = ""
    project_id: str | None = None  # written only when several projects share the name (AC2)
    cluster: str = ""
    provider: str = "aws"
    region: str = REGION_DEFAULT["aws"]
    network_cidr: str = "10.0.0.0/24"
    preset: str = "small"
    nodes: int = 3
    cpu: int = 4
    ram: int = 16
    support_plan: str = "developer pro"
    protect: bool = True
    office_hours: str | None = None
    timezone: str = TIMEZONE
    cidrs: list[str] = field(default_factory=list)
    allow_any_ip: bool = False
    bucket: str | None = None
    bucket_memory: int = 1024
    storage_backend: str = "magma"
    scopes: list[tuple[str, list[str]]] = field(default_factory=list)
    credential: str | None = None
    access: str = "read-write"
    password_env: str = ""


# ------------------------------------------------------------- the document
def size_of(a: Answers) -> dict[str, Any]:
    """The chosen preset from presets.yaml, or the custom size."""
    if a.preset == "custom":
        return {"configurationType": "multiNode", "availability": "multi", "numOfNodes": a.nodes, "cpu": a.cpu,
                "ram": a.ram, "services": ["data", "index", "query"]}
    return dict(load_presets()[a.preset])


def build_document(a: Answers) -> dict[str, Any]:
    size = size_of(a)
    cluster: dict[str, Any] = {"name": a.cluster}
    if is_single_node(size):
        cluster["configurationType"] = "singleNode"
    cluster["cloudProvider"] = {"type": a.provider, "region": a.region, "cidr": a.network_cidr}
    cluster["availability"] = {"type": size["availability"]}
    cluster["support"] = {"plan": a.support_plan, "timezone": "PT"}
    cluster["serviceGroups"] = [{
        "node": {"compute": {"cpu": size["cpu"], "ram": size["ram"]}, "disk": dict(DISK_DEFAULT[a.provider])},
        "numOfNodes": size["numOfNodes"],
        "services": sorted(size["services"]),
    }]
    cluster["deletionProtection"] = a.protect
    if a.office_hours:
        cluster["hibernation"] = {"timezone": a.timezone, "weekdays": a.office_hours, "weekend": "off"}
    if a.cidrs:
        if a.allow_any_ip:
            cluster["allowAnyIp"] = True
        cluster["allowedCidrs"] = [{"cidr": c} for c in a.cidrs]
    if a.bucket:
        bucket: dict[str, Any] = {"name": a.bucket, "memoryAllocationInMb": a.bucket_memory,
                                  "storageBackend": a.storage_backend}
        if a.scopes:
            bucket["scopes"] = [{"name": s, **({"collections": [{"name": c} for c in cs]} if cs else {})}
                                for s, cs in a.scopes]
        cluster["buckets"] = [bucket]
        if a.credential:
            cluster["databaseCredentials"] = [{
                "name": a.credential,
                "password": f"${{{password_env_of(a)}}}",
                "access": [{"privileges": ACCESS[a.access], "resources": {"buckets": [{"name": a.bucket}]}}],
            }]
    project: dict[str, Any] = {"name": a.project}
    if a.project_id:
        project = {"id": a.project_id, **project}
    return {"apiVersion": API_VERSION, "organizationId": a.org_id, "project": project, "clusters": [cluster]}


def render(a: Answers) -> str:
    """The document as YAML, with a header and a comment above each section."""
    from capellactl.importer import dump_yaml

    org = f" for organization {a.org_name} ({a.org_id})" if a.org_name else f" for organization {a.org_id}"
    lines: list[str] = []
    done: set[str] = set()
    for line in dump_yaml(build_document(a)).splitlines():
        m = re.match(r"^( {0,4})(- )?([A-Za-z]+):", line)
        if m and m.group(3) in COMMENTS and m.group(3) not in done and not m.group(2):
            done.add(m.group(3))
            lines.append(f"{m.group(1)}# {COMMENTS[m.group(3)]}")
        lines.append(line)
    return HEADER.replace("__ORG__", org) + "\n".join(lines) + "\n"


def issues(state: AppState, a: Answers) -> list[ConfigIssue]:
    """CAP-002 validation of the document built from the answers so far (offline)."""
    env = dict(state.env)
    if a.credential:
        env[password_env_of(a)] = PLACEHOLDER
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "capella.yaml"
        p.write_text(render(a), encoding="utf-8")
        try:
            load_config(p, env=env)
        except ConfigError as exc:
            return exc.issues
    return []


def _about(i: ConfigIssue, prefixes: tuple[str, ...]) -> bool:
    return any(i.path == p or i.path.startswith((p + ".", p + "[")) for p in prefixes)


def _message(i: ConfigIssue) -> str:
    return f"{i.path}: {i.message}"


# ------------------------------------------------------------ the questions
class Wizard:
    """Asks the questions (interactive) or takes the flags (non-interactive), validating as it goes."""

    def __init__(self, state: AppState, interactive: bool) -> None:
        self.state = state
        self.interactive = interactive
        self.a = Answers()

    def ask(self, setter: Callable[[Any], None], prompt: Callable[[], Any], about: tuple[str, ...],
            check: Callable[[Any], list[str]] | None = None) -> None:
        """Ask until the answer validates: the CAP-002 messages for `about` paths, then any extra `check`."""
        while True:
            value = prompt()
            problems = check(value) if check else []
            if not problems:
                setter(value)
                problems = [_message(i) for i in issues(self.state, self.a) if _about(i, about)]
            if not problems:
                return
            for p in problems:
                err(p)
            err("Please answer again.")

    def finish(self) -> None:
        """Non-interactive (and a last check interactively): the whole file must validate."""
        found = issues(self.state, self.a)
        if found:
            raise CliExit(ExitCode.CONFIG_INVALID, "\n".join(_message(i) for i in found), topic=found[0].topic)


def _prompt(text: str, default: Any = None, kind: Any = str, choices: list[str] | None = None) -> Callable[[], Any]:
    t = click.Choice(choices) if choices else kind
    return lambda: console.ask(text, default, type=t, show_choices=bool(choices),
                               show_default=default not in (None, ""))


def parse_cidrs(text: str) -> list[str]:
    return [c.strip() for c in re.split(r"[,\s]+", text or "") if c.strip()]


def canonical_or_raw(cidr: str) -> str:
    try:
        return normalize_cidr(cidr)
    except ValueError:
        return cidr  # validation reports it


def parse_scopes(items: list[str]) -> list[tuple[str, list[str]]]:
    """['inventory:items,suppliers', 'billing'] → [('inventory', ['items', 'suppliers']), ('billing', [])]."""
    out = []
    for item in items:
        for part in item.split(";"):
            if not part.strip():
                continue
            scope, _, colls = part.partition(":")
            out.append((scope.strip(), [c.strip() for c in colls.split(",") if c.strip()]))
    return out


def default_password_env(credential: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", credential).upper() + "_PASSWORD"


def password_env_of(a: Answers) -> str:
    return a.password_env or default_password_env(a.credential or "")


def _env_name_check(value: str) -> list[str]:
    return [] if ENV_NAME.match(value) else [f"{value} is not an environment variable name (letters, digits, _)"]


# ------------------------------------------------- organization and project
def _choose(items: list[dict[str, Any]], label: str, default_id: str | None) -> dict[str, Any]:
    for i, item in enumerate(items, 1):
        out(f"  {i}. {item.get('name')} ({item.get('id')})")
    default = next((i for i, it in enumerate(items, 1) if it.get("id") == default_id), 1)
    idx = int(console.ask(label, default, type=click.IntRange(1, len(items))))
    return items[idx - 1]


def organization(state: AppState, org_flag: str | None, interactive: bool,
                 missing: list[str]) -> tuple[CapellaClient | None, str, str | None]:
    """(client or None, organization id, organization name). Lists organizations when an API key is available."""
    s = state.settings()
    key = s.api_key.value
    default_org = org_flag or (str(s.org_id.value) if s.org_id.value else None)
    if not key:
        err("No API key found, so init cannot list your organizations and projects (run 'capellactl configure' "
            "to save one). Type the organization ID instead.")
        if org_flag or (default_org and not interactive):
            return None, str(default_org), None
        if not interactive:
            missing.append("--org-id")
            return None, "", None
        return None, str(console.ask("Organization ID", default_org, flag="--org-id")).strip(), None
    base_url = str(s.base_url.value)
    orgs = ep.list_organizations(CapellaClient(str(key), None, base_url, clock=get_clock()))
    chosen: dict[str, Any] | None = None
    if org_flag:
        chosen = next((o for o in orgs if o.get("id") == org_flag), {"id": org_flag})
    elif len(orgs) == 1:
        chosen = orgs[0]
    elif orgs and interactive:
        out("Organizations:")
        chosen = _choose(orgs, "Organization", default_org)
    elif default_org:
        chosen = next((o for o in orgs if o.get("id") == default_org), {"id": default_org})
    if chosen is None:
        missing.append("--org-id")
        return None, "", None
    org_id, org_name = str(chosen["id"]), chosen.get("name")
    out(f"Organization: {org_name} ({org_id})" if org_name else f"Organization: {org_id}")
    return CapellaClient(str(key), org_id, base_url, clock=get_clock()), org_id, org_name


def project_choice(client: CapellaClient | None, wanted: str | None, wanted_id: str | None,
                   interactive: bool) -> tuple[str, str | None, list[dict[str, Any]]]:
    """(project name, id to pin when ambiguous, its clusters in Capella). Lists projects when there is a client."""
    projects = ep.list_projects(client) if client is not None else []
    if wanted_id:
        found = [p for p in projects if p.get("id") == wanted_id]
        if not found:
            raise CliExit(ExitCode.CONFIG_INVALID, f"project {wanted_id} not found")
        wanted = str(found[0].get("name"))
    if interactive and not wanted:
        if projects:
            out("Existing projects:")
            for i, p in enumerate(projects, 1):
                out(f"  {i}. {p.get('name')}")
        answer = str(console.ask("Project (number of an existing project, or a new name)", flag="--project")).strip()
        if answer.isdigit() and 1 <= int(answer) <= len(projects):
            chosen = projects[int(answer) - 1]
            same = [p for p in projects if p.get("name") == chosen.get("name")]
            pin = str(chosen["id"]) if len(same) > 1 else None
            return str(chosen.get("name")), pin, ep.list_clusters(client, str(chosen["id"])) if client else []
        wanted = answer
    assert wanted is not None
    same = [p for p in projects if p.get("name") == wanted]
    if wanted_id:
        same = [p for p in same if p.get("id") == wanted_id]
    if len(same) > 1:
        if not interactive:
            ids = ", ".join(str(p.get("id")) for p in same)
            raise CliExit(ExitCode.CONFIG_INVALID, f"{len(same)} projects are named {wanted} (ids: {ids}); pass "
                                                   "--project-id", topic="idempotency")
        out(f"{len(same)} projects are named {wanted}:")
        chosen = _choose(same, "Which one", None)
        return wanted, str(chosen["id"]), ep.list_clusters(client, str(chosen["id"])) if client else []
    if same:
        pin = str(same[0]["id"]) if wanted_id and len([p for p in projects if p.get("name") == wanted]) > 1 else None
        return wanted, pin, ep.list_clusters(client, str(same[0]["id"])) if client else []
    if client is not None:
        out(f"Project {wanted} does not exist yet; apply will create it.")
    return wanted, None, []


# ----------------------------------------------------------------- command
@click.command("init", epilog="\b\nExamples:\n  capellactl init\n  capellactl init --dry-run\n"
                              "  capellactl init --non-interactive --org-id ORG --project nova-dev --cluster "
                              "nova-dev-01 \\\n      --provider aws --region us-east-1 --preset small "
                              "--hibernation office-hours --timezone US/Pacific --cidr 203.0.113.10/32")
@click.option("--file", "file", metavar="PATH", help="Output file (default: capella.yaml; .yml accepted).")
@click.option("--non-interactive", is_flag=True, help="Take every answer from flags; never prompt.")
@click.option("--dry-run", is_flag=True, help="Print the YAML instead of writing the file.")
@click.option("--force", is_flag=True, help="Overwrite an existing file without asking (a .bak is kept).")
@click.option("--org-id", metavar="ID", help="Organization ID (default: from the API key, profile or CAPELLA_ORG_ID).")
@click.option("--project", metavar="NAME", help="Project name (new or existing).")
@click.option("--project-id", metavar="ID", help="Existing project, when several share a name.")
@click.option("--cluster", metavar="NAME", help="Cluster name.")
@click.option("--provider", type=click.Choice(PROVIDERS), help="Cloud provider (default aws).")
@click.option("--region", help="Region (default per provider).")
@click.option("--network-cidr", metavar="CIDR", help="Cluster network (default: first free 10.x.y.0/24).")
@click.option("--preset", type=click.Choice([*load_presets(), "custom"]), help="Size preset from presets.yaml "
              "(default small).")
@click.option("--nodes", type=int, help="With --preset custom: nodes.")
@click.option("--cpu", type=int, help="With --preset custom: vCPUs per node.")
@click.option("--ram", type=int, help="With --preset custom: RAM GB per node.")
@click.option("--support-plan", type=click.Choice(SUPPORT_PLANS), help="Support plan (default developer pro).")
@click.option("--protect/--no-protect", "protect", default=None, help="Deletion protection (default on).")
@click.option("--hibernation", type=click.Choice(["none", "office-hours"]), help="Turn the cluster off outside "
              "office hours (default none).")
@click.option("--office-hours", metavar="HH:MM-HH:MM", help=f"Weekday on-window (default {OFFICE_HOURS}).")
@click.option("--timezone", help=f"Hibernation timezone (default {TIMEZONE}).")
@click.option("--cidr", "cidrs", multiple=True, metavar="CIDR", help="Allowed IP range (repeatable).")
@click.option("--allow-any-ip", is_flag=True, help="Required with --cidr 0.0.0.0/0.")
@click.option("--bucket", metavar="NAME", help="Add a bucket.")
@click.option("--bucket-memory", type=int, help="Bucket memory in MB (default 1024).")
@click.option("--storage-backend", type=click.Choice(["magma", "couchstore"]), help="Bucket storage (default magma).")
@click.option("--scope", "scopes", multiple=True, metavar="SCOPE[:COLL,…]", help="Scope and collections (repeatable).")
@click.option("--credential", metavar="NAME", help="Add an app credential with access to the bucket.")
@click.option("--access", type=click.Choice(list(ACCESS)), help="Credential access (default read-write).")
@click.option("--password-env", metavar="VAR", help="Environment variable holding the credential password "
              "(default NAME_PASSWORD).")
@pass_state
def init(state: AppState, file: str | None, non_interactive: bool, dry_run: bool, force: bool, org_id: str | None,
         project: str | None, project_id: str | None, cluster: str | None, provider: str | None, region: str | None,
         network_cidr: str | None, preset: str | None, nodes: int | None, cpu: int | None, ram: int | None,
         support_plan: str | None, protect: bool | None, hibernation: str | None, office_hours: str | None,
         timezone: str | None, cidrs: tuple[str, ...], allow_any_ip: bool, bucket: str | None,
         bucket_memory: int | None, storage_backend: str | None, scopes: tuple[str, ...], credential: str | None,
         access: str | None, password_env: str | None) -> None:
    """Create capella.yaml by answering a few questions (or from flags with --non-interactive)."""
    interactive = console.is_interactive() and not non_interactive
    path = Path(file) if file else state.config_path()
    if path.exists() and not dry_run and not force:
        if not interactive:
            raise CliExit(ExitCode.ERROR, f"{path.name} exists; pass --force to overwrite it (the current file is "
                                          f"kept as {path.name}.bak)")
        if not console.ask_yes_no(f"{path.name} exists. Overwrite?", False):
            out("Nothing was written.")
            return

    if interactive:
        start = console.ask("Start from: a new environment, or an existing Capella project", "new",
                            type=click.Choice(["new", "import"]))
        if start == "import":
            _import(state, path, org_id)
            return

    missing: list[str] = []
    client, org, org_name = organization(state, org_id, interactive, missing)
    if not interactive:
        missing += [f for f, v in (("--project", project or project_id), ("--cluster", cluster)) if not v]
        if missing:
            raise CliExit(ExitCode.CONFIG_INVALID, f"missing required options for --non-interactive: "
                                                   f"{', '.join(missing)}", topic="getting-started")
    w = Wizard(state, interactive)
    a = w.a
    a.org_id, a.org_name = org, org_name
    a.project, a.project_id, existing = project_choice(client, project, project_id, interactive)
    used = [str((c.get("cloudProvider") or {}).get("cidr", "")) for c in existing]
    taken = {str(c.get("name")) for c in existing}

    def free_name(v: str) -> list[str]:
        return [f"cluster {v} already exists in project {a.project}; use 'capellactl import' to describe it, or "
                "choose another name"] if v in taken else []

    a.provider = provider or "aws"
    a.region = region or REGION_DEFAULT[a.provider]
    a.network_cidr = network_cidr or suggest_cidr(used)
    a.preset = preset or "small"
    a.nodes, a.cpu, a.ram = nodes or 3, cpu or 4, ram or 16
    a.support_plan = support_plan or "developer pro"
    a.protect = True if protect is None else protect
    a.office_hours = (office_hours or OFFICE_HOURS) if hibernation == "office-hours" else None
    a.timezone = timezone or TIMEZONE
    a.cidrs = [canonical_or_raw(c) for c in cidrs]
    a.allow_any_ip = allow_any_ip
    a.bucket = bucket
    a.bucket_memory = bucket_memory or 1024
    a.storage_backend = storage_backend or "magma"
    a.scopes = parse_scopes(list(scopes))
    a.credential = credential
    a.access = access or "read-write"
    a.password_env = password_env or (default_password_env(credential) if credential else "")
    a.cluster = cluster or f"{a.project}-01"

    if not interactive:
        problems = free_name(a.cluster) + (_env_name_check(password_env_of(a)) if a.credential else [])
        if problems:
            raise CliExit(ExitCode.CONFIG_INVALID, "\n".join(problems))
        w.finish()
    else:
        _interview(w, free_name, region_given=region is not None)
        w.finish()

    text = render(a)
    if dry_run:
        out(text.rstrip("\n"))
        return
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        note(f"previous file saved as {backup.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    out(f"✔ Wrote {path} (validated)")
    if a.credential:
        out(f"Next: export {password_env_of(a)}=…   then   capellactl plan")
    else:
        out("Next: capellactl plan")


def _interview(w: Wizard, free_name: Callable[[str], list[str]], region_given: bool) -> None:
    """The questions of the interactive flow, in order; the defaults come from flags or built-in defaults."""
    a = w.a

    def set_(name: str) -> Callable[[Any], None]:
        return lambda v: setattr(a, name, v)

    w.ask(set_("cluster"), _prompt("Cluster name", a.cluster), ("clusters[0].name",), free_name)
    w.ask(set_("provider"), _prompt("Cloud provider", a.provider, choices=PROVIDERS), ("clusters[0].cloudProvider.type",))
    if not region_given:
        a.region = REGION_DEFAULT[a.provider]
    w.ask(set_("region"), _prompt("Region", a.region), ("clusters[0].cloudProvider.region",))
    w.ask(set_("network_cidr"), _prompt("Cluster network (must not overlap other clusters)", a.network_cidr),
          ("clusters[0].cloudProvider.cidr",))
    presets = [*load_presets(), "custom"]
    out("Size presets: " + "; ".join(f"{k} ({v.get('description', '')})" for k, v in load_presets().items()))
    w.ask(set_("preset"), _prompt("Size preset", a.preset, choices=presets),
          ("clusters[0].cloudProvider.type", "clusters[0].configurationType", "clusters[0].availability",
           "clusters[0].serviceGroups"))
    if a.preset == "custom":
        group = ("clusters[0].serviceGroups",)
        w.ask(set_("nodes"), _prompt("Nodes", a.nodes, int), group)
        w.ask(set_("cpu"), _prompt("vCPUs per node", a.cpu, int), group)
        w.ask(set_("ram"), _prompt("RAM GB per node", a.ram, int), group)
    w.ask(set_("support_plan"), _prompt("Support plan", a.support_plan, choices=SUPPORT_PLANS), ("clusters[0].support",))
    w.ask(set_("protect"), lambda: console.ask_yes_no("Protect from deletion?", bool(a.protect)),
          ("clusters[0].deletionProtection",))
    hibernate = console.ask_yes_no("Hibernate outside office hours (weekdays only)?", a.office_hours is not None)
    if hibernate:
        a.office_hours = a.office_hours or OFFICE_HOURS
        w.ask(set_("office_hours"), _prompt("Weekday on-window (HH:MM-HH:MM, minutes 00 or 30)", a.office_hours),
              ("clusters[0].hibernation.weekdays",))
        w.ask(set_("timezone"), _prompt("Timezone", a.timezone), ("clusters[0].hibernation.timezone",))
    else:
        a.office_hours = None

    def cidrs(v: str) -> None:
        a.cidrs = [canonical_or_raw(c) for c in parse_cidrs(v)]
        if any(c in ("0.0.0.0/0", "::/0") for c in a.cidrs):
            a.allow_any_ip = console.ask_yes_no("0.0.0.0/0 lets any IP address connect. Allow it?", False)

    w.ask(cidrs, _prompt("Allowed IP ranges (CIDR, comma-separated; empty: none)", ",".join(a.cidrs)),
          ("clusters[0].allowedCidrs",))

    w.ask(lambda v: setattr(a, "bucket", v.strip() or None), _prompt("Add a bucket now? Bucket name (empty: none)",
                                                                      a.bucket or ""), ("clusters[0].buckets",))
    if a.bucket:
        w.ask(set_("bucket_memory"), _prompt("Bucket memory (MB)", a.bucket_memory, int), ("clusters[0].buckets",))
        w.ask(set_("storage_backend"), _prompt("Storage backend", a.storage_backend, choices=["magma", "couchstore"]),
              ("clusters[0].buckets",))
        current = ";".join(f"{s}:{','.join(cs)}" if cs else s for s, cs in a.scopes)
        w.ask(lambda v: setattr(a, "scopes", parse_scopes([v])),
              _prompt("Scopes and collections (scope:coll1,coll2;scope2; empty: none)", current),
              ("clusters[0].buckets",))
        w.ask(lambda v: setattr(a, "credential", v.strip() or None),
              _prompt("Add an app credential? Name (empty: none)", a.credential or ""),
              ("clusters[0].databaseCredentials",))
        if a.credential:
            w.ask(set_("access"), _prompt(f"Access to {a.bucket}", a.access, choices=list(ACCESS)),
                  ("clusters[0].databaseCredentials",))
            w.ask(set_("password_env"), _prompt("Password environment variable",
                                                a.password_env or default_password_env(a.credential)),
                  ("clusters[0].databaseCredentials",), _env_name_check)
    else:
        a.credential = None


def _import(state: AppState, path: Path, org_flag: str | None) -> None:
    """The 'existing Capella project' path: choose the project (and clusters) and run `import` (AC8)."""
    from capellactl.cli.env import run_import

    missing: list[str] = []
    client, _, _ = organization(state, org_flag, True, missing)
    if client is None:
        raise CliExit(ExitCode.CONFIG_INVALID, "importing needs an API key; run 'capellactl configure' first",
                      topic="environment")
    projects = ep.list_projects(client)
    if not projects:
        raise CliExit(ExitCode.ERROR, "this organization has no projects to import; choose 'new' instead")
    out("Projects:")
    chosen = _choose(projects, "Project to import", None)
    names = str(console.ask("Clusters to import (comma-separated names; empty: all)", "", show_default=False))
    clusters = tuple(n.strip() for n in names.split(",") if n.strip())
    run_import(state, client, project_id=str(chosen["id"]), clusters=clusters, file=str(path), force=True)
