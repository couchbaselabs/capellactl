"""Write capella.yaml from what exists in Capella (CAP-036).

Read-only: only GET requests. Each exporter is the inverse of a reconciler's comparison, so a plan
straight after an import reports no changes (CAP-036 AC2). Passwords are never exported (Capella never
returns them) and the API Key Token is never written.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import yaml

from capellactl import __version__
from capellactl.api import endpoints as ep
from capellactl.api.client import CapellaClient
from capellactl.api.errors import CapellaApiError
from capellactl.config.loader import BUCKET_DEFAULTS

NEW_CLUSTER_TEMPLATE = """\
# This project has no clusters yet. To create one, run: capellactl cluster create NAME
"""
NO_PROJECTS_TEMPLATE = """\
# No projects left in Capella. Create one with: capellactl project create NAME
# or add an existing one with: capellactl import --project NAME
"""


DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DISK_KEYS = ("type", "storage", "iops", "autoExpansion")
SYSTEM_SCOPES = {"_system"}


@dataclass
class ImportResult:
    data: dict[str, Any]
    comments: dict[str, str] = field(default_factory=dict)   # placeholder key -> comment text
    blocks: dict[str, str] = field(default_factory=dict)     # placeholder key -> commented-out YAML block
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


class _Skip(Exception):
    pass


class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def next(self, kind: str) -> str:
        self.n += 1
        return f"__{kind}_{self.n}__"


# ---------------------------------------------------------------- exporters
def _is_free(body: dict[str, Any]) -> bool:
    return str((body.get("support") or {}).get("plan", "")).lower() == "free"


def export_free_cluster(body: dict[str, Any], full: bool) -> dict[str, Any]:
    """Free tier: only name, description and cloud provider are configurable; the id is always recorded."""
    out: dict[str, Any] = {"id": body["id"], "name": body["name"]}
    if body.get("description") or full:
        out["description"] = body.get("description", "")
    out["tier"] = "free"
    cp = body.get("cloudProvider") or {}
    out["cloudProvider"] = {k: cp[k] for k in ("type", "region", "cidr") if cp.get(k)}
    return out


def export_cluster(body: dict[str, Any], full: bool, pin_id: bool) -> dict[str, Any]:
    if _is_free(body):
        return export_free_cluster(body, full)
    out: dict[str, Any] = {}
    if pin_id:
        out["id"] = body["id"]
    out["name"] = body["name"]
    if body.get("description") or full:
        out["description"] = body.get("description", "")
    if body.get("configurationType", "multiNode") != "multiNode" or full:
        out["configurationType"] = body.get("configurationType", "multiNode")
    cp = body.get("cloudProvider") or {}
    out["cloudProvider"] = {k: cp[k] for k in ("type", "region", "cidr") if cp.get(k)}
    version = (body.get("couchbaseServer") or {}).get("version")
    if version:
        out["couchbaseServer"] = {"version": version}
    out["availability"] = {"type": (body.get("availability") or {}).get("type", "multi")}
    support = body.get("support") or {}
    out["support"] = {k: support[k] for k in ("plan", "timezone") if support.get(k)}
    groups = []
    for g in body.get("serviceGroups") or []:
        node = g.get("node") or {}
        disk = {k: node.get("disk", {})[k] for k in DISK_KEYS if k in (node.get("disk") or {})}
        groups.append({
            "node": {"compute": {"cpu": (node.get("compute") or {}).get("cpu"),
                                 "ram": (node.get("compute") or {}).get("ram")},
                     "disk": disk},
            "numOfNodes": g.get("numOfNodes"),
            "services": sorted(g.get("services") or []),
        })
    out["serviceGroups"] = groups
    if body.get("cmekId"):
        out["cmekId"] = body["cmekId"]
    if body.get("enablePrivateDNSResolution") or (full and "enablePrivateDNSResolution" in body):
        out["enablePrivateDNSResolution"] = bool(body.get("enablePrivateDNSResolution"))
    if body.get("deletionProtection") or full:
        out["deletionProtection"] = bool(body.get("deletionProtection"))
    return out


def _hhmm(b: dict[str, Any] | None, end: bool = False) -> str:
    h, m = int((b or {}).get("hour", 0)), int((b or {}).get("minute", 0))
    if end and h == 0 and m == 0:
        return "24:00"
    return f"{h:02d}:{m:02d}"


def _day_value(d: dict[str, Any]) -> str:
    state = d.get("state")
    if state in ("on", "off"):
        return str(state)
    return f"{_hhmm(d.get('from'))}-{_hhmm(d.get('to'), end=True)}"


def export_schedule(body: dict[str, Any]) -> dict[str, Any]:
    """API form (7 days, Monday→Sunday) → friendly form; compacts weekdays/weekend when uniform (AC7)."""
    by_day = {d.get("day"): _day_value(d) for d in body.get("days") or []}
    out: dict[str, Any] = {"timezone": body.get("timezone")}
    overrides: dict[str, str] = {}
    for group, days in (("weekdays", DAYS[:5]), ("weekend", DAYS[5:])):
        values = [by_day[d] for d in days if d in by_day]
        if not values:
            continue
        common = max(values, key=lambda v: (values.count(v), -values.index(v)))  # ties: the earliest day's value
        out[group] = common  # the most common value, plus overrides for the other days (as `schedule set` writes)
        overrides.update({d: by_day[d] for d in days if d in by_day and by_day[d] != common})
    out.update(overrides)
    if body.get("activationStatus") == "paused":
        out["paused"] = True
    return out


def export_cidr(c: dict[str, Any]) -> dict[str, Any]:
    out = {"cidr": c["cidr"]}
    if c.get("comment"):
        out["comment"] = c["comment"]
    if c.get("expiresAt"):
        out["expiresAt"] = c["expiresAt"]
    return out


BUCKET_FIELDS = ("type", "storageBackend", "vbuckets", "memoryAllocationInMb", "bucketConflictResolution",
                 "durabilityLevel", "replicas", "flushEnabled", "timeToLiveInSeconds", "evictionPolicy", "priority",
                 "enableCrossClusterVersioning")


def export_bucket(b: dict[str, Any], scopes: list[dict[str, Any]] | None, full: bool) -> dict[str, Any]:
    src = dict(b)
    if "flushEnabled" not in src and "flush" in src:
        src["flushEnabled"] = bool(src["flush"])
    out: dict[str, Any] = {"name": b["name"]}
    for f in BUCKET_FIELDS:
        if f not in src or src[f] is None:
            continue
        if f == "storageBackend" and src.get("type") == "ephemeral":
            continue
        if not full:
            if f in BUCKET_DEFAULTS and src[f] == BUCKET_DEFAULTS[f]:
                continue
            if f == "priority" and not src[f]:
                continue
            if f == "enableCrossClusterVersioning" and not src[f]:
                continue
        out[f] = src[f]
    exported_scopes = []
    for s in scopes or []:
        name = s.get("name")
        if name in SYSTEM_SCOPES:
            continue
        colls = [c for c in s.get("collections") or [] if not (name == "_default" and c.get("name") == "_default")]
        if name == "_default" and not colls:
            continue
        entry: dict[str, Any] = {"name": name}
        if colls:
            entry["collections"] = [
                {"name": c["name"], **({"maxTTL": c["maxTTL"]} if full or c.get("maxTTL") not in (None, 0) else {})}
                for c in colls
            ]
        exported_scopes.append(entry)
    if exported_scopes:
        out["scopes"] = exported_scopes
    return out


def export_credential(u: dict[str, Any]) -> dict[str, Any]:
    from capellactl.resources.credential import without_wildcards

    access = []
    for a in without_wildcards(u.get("access")):
        entry: dict[str, Any] = {"privileges": sorted(a.get("privileges") or [])}
        res = a.get("resources")
        if res and res.get("buckets"):
            buckets = []
            for b in res["buckets"]:
                rb: dict[str, Any] = {"name": b["name"]}
                if b.get("scopes"):
                    rb["scopes"] = [{"name": s["name"], **({"collections": list(s["collections"])}
                                                           if s.get("collections") else {})} for s in b["scopes"]]
                buckets.append(rb)
            entry["resources"] = {"buckets": buckets}
        access.append(entry)
    return {"name": u["name"], "access": access}


def is_advanced(u: dict[str, Any]) -> bool:
    return bool(u.get("userRoles")) or u.get("credentialType") == "advanced"


# ------------------------------------------------------------------- driver
def build_document(
    client: CapellaClient,
    project: dict[str, Any],
    clusters: list[dict[str, Any]],
    full: bool = False,
    all_clusters: list[dict[str, Any]] | None = None,
    known_access: Callable[[str, str], tuple[Any, Any] | None] | None = None,
) -> ImportResult:
    """Read everything below `project` for the given clusters and build the config document.

    `all_clusters` (every cluster in the project) decides which names are ambiguous and need an id: pin,
    even when only some clusters are exported. `known_access(cluster, credential)` (sync) returns the access the
    current file records, used for a credential that has no access in Capella so `apply` can restore it.
    """
    ids = _Ids()
    res = ImportResult(data={})
    counts = {"cluster": 0, "bucket": 0, "scope": 0, "collection": 0, "credential": 0, "allowed CIDR": 0,
              "hibernation schedule": 0}
    pid = str(project["id"])
    name_counts: dict[str, int] = {}
    for c in all_clusters if all_clusters is not None else clusters:
        name_counts[c["name"]] = name_counts.get(c["name"], 0) + 1

    exported_clusters: list[dict[str, Any]] = []
    for c in clusters:
        cid = str(c["id"])
        free = _is_free(c)
        body, _ = (ep.get_free_cluster if free else ep.get_cluster)(client, pid, cid)
        ambiguous = name_counts[body["name"]] > 1
        msg = f"{name_counts[body['name']]} clusters are named {body['name']}; each is pinned with id:"
        if ambiguous and msg not in res.warnings:
            res.warnings.append(msg)
        cl = export_cluster(body, full, pin_id=True)
        counts["cluster"] += 1
        state = str(body.get("currentState", ""))

        def guarded(what: str, fn: Any, *args: Any, _cl: dict[str, Any] = cl, _state: str = state,
                    _name: str = body["name"]) -> Any:
            try:
                return fn(*args)
            except CapellaApiError as exc:
                note = ids.next("comment")
                _cl[note] = (f"not imported: {what} (Capella returned {exc.http_status} while the cluster is "
                             f"{_state or 'unavailable'};\nrun capellactl import again when it is on)")
                res.warnings.append(f"cluster {_name}: {what} not imported ({exc.http_status})")
                return None

        try:
            if free:  # no on/off schedule on the free tier
                raise _Skip
            sched, _ = ep.get_schedule(client, pid, cid)
        except _Skip:
            sched = None
        except CapellaApiError as exc:
            sched = None
            if exc.http_status != 404:
                res.warnings.append(f"cluster {body['name']}: hibernation schedule not imported ({exc.http_status})")
        if sched:
            cl["hibernation"] = export_schedule(sched)
            counts["hibernation schedule"] += 1

        cidrs = guarded("allowed CIDRs", ep.list_allowed_cidrs, client, pid, cid)
        if cidrs:
            active = [export_cidr(x) for x in cidrs if x.get("status", "active") != "expired"]
            if active:
                cl["allowedCidrs"] = active
                counts["allowed CIDR"] += len(active)

        if free:
            buckets = guarded("buckets", lambda *a: ep.list_free_buckets(*a)[0], client, pid, cid)
        else:
            buckets = guarded("buckets", ep.list_buckets, client, pid, cid)
        if buckets:
            exported = []
            for b in buckets:
                if free:  # only the memory quota (and cross-cluster versioning) can be set on free-tier buckets
                    eb = {"name": b["name"], "memoryAllocationInMb": b.get("memoryAllocationInMb", 100)}
                    if b.get("enableCrossClusterVersioning"):
                        eb["enableCrossClusterVersioning"] = True
                    exported.append(eb)
                    counts["bucket"] += 1
                    continue
                scopes = guarded(f"scopes of bucket {b['name']}", ep.list_scopes, client, pid, cid, b["id"])
                eb = export_bucket(b, scopes, full)
                exported.append(eb)
                counts["bucket"] += 1
                counts["scope"] += len(eb.get("scopes") or [])
                counts["collection"] += sum(len(s.get("collections") or []) for s in eb.get("scopes") or [])
            cl["buckets"] = exported

        users = guarded("database credentials", ep.list_credentials, client, pid, cid)
        if users:
            creds: list[Any] = []
            for u in users:
                if is_advanced(u):
                    key = ids.next("block")
                    res.blocks[key] = yaml.safe_dump(
                        [{"name": u["name"], "userRoles": u.get("userRoles") or []}], sort_keys=False).rstrip()
                    res.comments[key + "_why"] = (f"{u['name']} is an advanced credential (userRoles). capellactl 1.0 "
                                                  "manages basic\ncredentials only, so it is listed here for reference.")
                    creds.append({key + "_why": "", key: ""})
                    continue
                if not u.get("access"):  # basic, but its access was removed outside capellactl
                    kept_access = known_access(body["name"], u["name"]) if known_access else None
                    if kept_access:
                        note = ids.next("comment")
                        res.comments[note] = (f"{u['name']} has no access in Capella (removed outside capellactl); "
                                              "the access below is kept\nfrom the previous capella.yaml: run "
                                              "`capellactl apply` to restore it.")
                        creds.append({note: "", "name": u["name"], **({"password": kept_access[1]} if kept_access[1] else {}),
                                      "access": kept_access[0]})
                        res.warnings.append(f"credential {body['name']}/{u['name']} has no access in Capella; kept its "
                                            "access from capella.yaml (run 'capellactl apply' to restore it)")
                        counts["credential"] += 1
                        continue
                    key = ids.next("block")
                    res.blocks[key] = yaml.safe_dump([{"name": u["name"], "access": []}], sort_keys=False).rstrip()
                    res.comments[key + "_why"] = (
                        f"{u['name']} has no access in Capella, so it is listed here for reference. To give it access:\n"
                        f"  capellactl credential create {body['name']} {u['name']} --bucket BUCKET --password-env VAR")
                    creds.append({key + "_why": "", key: ""})
                    continue
                note = ids.next("comment")
                entry = {note: "", **export_credential(u)}
                res.comments[note] = (
                    "password not exported (Capella never returns it); the existing password is unchanged.\n"
                    f"To rotate later: add password: ${{{u['name'].upper()}_PASSWORD}} and run\n"
                    f"  capellactl credential update {body['name']} {u['name']} --rotate-password")
                creds.append(entry)
                counts["credential"] += 1
            cl["databaseCredentials"] = creds
        exported_clusters.append(cl)

    # Every project and cluster is pinned by id, so a rename in the Capella UI shows as a rename (CAP-048).
    proj: dict[str, Any] = {"id": pid, "name": project["name"]}
    if project.get("description") or full:
        proj["description"] = project.get("description", "")
    res.data = {"apiVersion": "capellactl/v1", "organizationId": client.org_id, "project": proj,
                "clusters": exported_clusters}
    res.counts = counts
    return res


def combine(results: list[ImportResult], org_id: str | None) -> ImportResult:
    """Several single-project results → one `projects:` document (CAP-040)."""
    out = ImportResult(data={"apiVersion": "capellactl/v1", "organizationId": org_id, "projects": []})
    counts: dict[str, int] = {"project": 0}
    for r in results:
        proj = dict(r.data.get("project") or {})
        proj["clusters"] = list(r.data.get("clusters") or [])
        out.data["projects"].append(proj)
        out.comments.update(r.comments)
        out.blocks.update(r.blocks)
        out.warnings.extend(w for w in r.warnings if w not in out.warnings)
        counts["project"] += 1
        for k, v in (r.counts or {}).items():
            counts[k] = counts.get(k, 0) + v
    out.counts = counts
    return out


def to_projects_form(data: dict[str, Any]) -> dict[str, Any]:
    """Single-project form → projects: form (for comparisons); projects: form is returned as is."""
    if "projects" in data or "project" not in data:
        return data
    out = {k: v for k, v in data.items() if k not in ("project", "clusters")}
    out["projects"] = [{**(data.get("project") or {}), "clusters": list(data.get("clusters") or [])}]
    return out


def _clusters_of(data: dict[str, Any]) -> list[dict[str, Any]]:
    if "projects" in data:
        return [c for p in data["projects"] or [] for c in p.get("clusters") or []]
    return list(data.get("clusters") or [])


class _Dumper(yaml.SafeDumper):
    """Indent list items under their key, like the hand-written examples."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        return super().increase_indent(flow, False)


class _FlowMap(dict):  # type: ignore[type-arg]
    pass


class _FlowList(list):  # type: ignore[type-arg]
    pass


_Dumper.add_representer(_FlowMap, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v, flow_style=True))
_Dumper.add_representer(_FlowList, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True))
FLOW_KEYS = {"compute", "disk", "services", "privileges", "cloudProvider", "availability", "support",
             "couchbaseServer"}


def _flow(obj: Any, key: str | None = None) -> Any:
    """Small leaf values (sizes, service lists, privileges) on one line, as in the examples."""
    if isinstance(obj, dict):
        if key in FLOW_KEYS and all(not isinstance(v, (dict, list)) for v in obj.values()):
            return _FlowMap(obj)
        return {k: _flow(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        if all(not isinstance(v, (dict, list)) for v in obj) and (key in FLOW_KEYS or key == "collections"):
            return _FlowList(obj)
        return [_flow(v) for v in obj]
    return obj


def dump_yaml(data: Any) -> str:
    """YAML in the house style: list items indented under their key, small leaf maps and lists on one line."""
    return yaml.dump(_flow(data), Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120)


_PLACEHOLDER = re.compile(r"^(\s*)(- )?(__(?:comment|block)_\d+__(?:_why)?): .*$")


def render(res: ImportResult, org_name: str | None = None) -> str:
    """YAML text with comments. Placeholder keys become comments or commented-out blocks."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    org = f"{org_name} ({res.data['organizationId']})" if org_name else str(res.data["organizationId"])
    if "projects" in res.data:
        names = [p.get("name") for p in res.data["projects"] or []]
    else:
        names = [res.data.get("project", {}).get("name")]
    label = ("no projects" if not names else f"project {names[0]}" if len(names) == 1
             else f"projects {', '.join(str(n) for n in names)}")
    header = [
        f"# Imported by capellactl {__version__} on {ts}",
        f"# Organization {org}, {label}.",
        "# Maintained by capellactl: change it with `capellactl cluster create|update|scale` and refresh it",
        "# with `capellactl sync`. `capellactl help config <field>` explains every field.",
        "",
    ]
    data = copy.deepcopy(res.data)
    comments = dict(res.comments)
    for cl in _clusters_of(data):
        for k in [k for k in cl if k.startswith("__comment_")]:
            comments[k] = cl[k]
            cl[k] = ""
    text = dump_yaml(data)
    out: list[str] = []
    pending: str | None = None
    for line in text.splitlines():
        m = _PLACEHOLDER.match(line)
        if m:
            indent, dash, key = m.group(1), m.group(2), m.group(3)
            if key in res.blocks:
                base = indent if dash else indent[:-2]
                out.extend(f"{base}# {bl}" for bl in res.blocks[key].splitlines())
                pending = None  # the commented block is the whole list item
                continue
            out.extend(f"{indent}# {c}" for c in comments.get(key, "").splitlines())
            if dash:
                pending = f"{indent}- "
            continue
        if pending is not None:
            out.append(pending + line.lstrip())
            pending = None
            continue
        out.append(line)
    return "\n".join(header + _empty_lists(out)) + "\n"


def _empty_lists(lines: list[str]) -> list[str]:
    """`key:` followed only by comments (every item commented out) would load as null: write `key: []`."""
    out = list(lines)
    for i, line in enumerate(out):
        if not line.rstrip().endswith(":") or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        j = i + 1
        while j < len(out) and out[j].lstrip().startswith("#") and len(out[j]) - len(out[j].lstrip()) > indent:
            j += 1
        nxt = out[j] if j < len(out) else ""
        if j > i + 1 and (not nxt.strip() or len(nxt) - len(nxt.lstrip()) <= indent):
            out[i] = line.rstrip() + " []"
    return out


def summary(res: ImportResult) -> str:
    c = res.counts

    def p(n: int, w: str) -> str:
        return f"{n} {w}" + ("" if n == 1 else ("s" if not w.endswith("CIDR") else "s"))

    return (f"Imported {p(c.get('project', 1), 'project')}, " + ", ".join(p(c.get(k, 0), k) for k in
            ("cluster", "bucket", "scope", "collection", "credential", "allowed CIDR", "hibernation schedule")))
