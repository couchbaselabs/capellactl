"""Cross-reference and multi-field rules that JSON Schema cannot express (CAP-002 AC4)."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from capellactl.output.password_gen import RULES, meets_rules

if TYPE_CHECKING:
    from capellactl.config.loader import Config, ConfigIssue  # noqa: F401

RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")
DAY_KEYS = ("weekdays", "weekend", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

FREE_TIER_REGIONS = {
    "aws": ["us-east-2", "eu-west-1", "ap-southeast-1"],
    "gcp": ["us-central1", "europe-west1", "asia-east1"],
    "azure": ["eastus", "swedencentral", "koreacentral"],
}
SINGLE_NODE_SERVICES = {"data", "index", "query", "search"}  # spec: configurationType singleNode
FREE_TIER_FORBIDDEN = ("configurationType", "couchbaseServer", "serviceGroups", "availability", "support", "zones",
                       "cmekId", "enablePrivateDNSResolution", "hibernation")
PROVISIONED_REQUIRED = ("availability", "support", "serviceGroups")

# Region naming per provider (shape only, so new regions pass): aws us-east-1, gcp us-east1, azure eastus.
REGION_SHAPES = {
    "aws": (re.compile(r"^[a-z]{2}(-gov)?-[a-z]+-\d+$"), "us-east-1, eu-west-1, ap-southeast-1"),
    "gcp": (re.compile(r"^[a-z]+-[a-z]+\d+$"), "us-east1, europe-west1, asia-east1"),
    "azure": (re.compile(r"^[a-z]+\d*$"), "eastus, westeurope, centralindia"),
}

DISK_TYPES = {
    "aws": {"gp3", "io2"},
    "azure": {"P6", "P10", "P15", "P20", "P30", "P40", "P50", "P60", "Ultra"},
    "gcp": {"pd-ssd"},
}


def _check_region(cl: dict[str, Any], cp: tuple[Any, ...], add: Any) -> None:
    prov = (cl.get("cloudProvider") or {}).get("type")
    region = (cl.get("cloudProvider") or {}).get("region")
    if prov not in REGION_SHAPES or not isinstance(region, str) or "${" in region:
        return
    shape, examples = REGION_SHAPES[prov]
    if not shape.match(region):
        other = next((p for p, (s, _) in REGION_SHAPES.items() if p != prov and s.match(region)), None)
        def a(p: str) -> str:
            return f"an {p}" if p[0] in "aeiou" else f"a {p}"
        looks = f"; it looks like {a(other)} region" if other else ""
        add(cp + ("cloudProvider", "region"),
            f"{region} is not {a(prov)} region name{looks} ({prov} regions look like {examples})")


def normalize_cidr(value: str) -> str:
    """Canonical form; a bare IP becomes /32 (or /128). Raises ValueError for host bits set."""
    text = value.strip()
    if "/" not in text:
        text += "/128" if ":" in text else "/32"
    return str(ipaddress.ip_network(text, strict=True))


FREE_TIER_BUCKET_FIELDS = ("name", "memoryAllocationInMb", "enableCrossClusterVersioning", "scopes")
EPHEMERAL_EVICTION = ("noEviction", "nruEviction")
EPHEMERAL_DURABILITY = ("none", "majority")


def bucket_type_rules(b: dict[str, Any]) -> list[tuple[str, str]]:
    """(field, message) for settings the bucket type does not allow (CAP-023 AC5)."""
    issues = []
    ephemeral = b.get("type") == "ephemeral"
    eviction = b.get("evictionPolicy")
    if ephemeral:
        if "storageBackend" in b:
            issues.append(("storageBackend", "not allowed for ephemeral buckets (they keep data in memory only)"))
        if eviction and eviction not in EPHEMERAL_EVICTION:
            issues.append(("evictionPolicy", f"{eviction} is not valid for ephemeral buckets (use noEviction or "
                                             "nruEviction)"))
        durability = b.get("durabilityLevel")
        if durability and durability not in EPHEMERAL_DURABILITY:
            issues.append(("durabilityLevel", f"{durability} needs disk persistence; ephemeral buckets allow none "
                                              "or majority"))
    elif eviction and eviction != "fullEviction":
        issues.append(("evictionPolicy", f"{eviction} is only valid for ephemeral buckets (couchbase buckets use "
                                         "fullEviction)"))
    if "vbuckets" in b and b.get("storageBackend") != "magma":
        issues.append(("vbuckets", "only allowed with storageBackend: magma"))
    return issues


KEYSPACE_NAME = re.compile(r"^[A-Za-z0-9_%-]{1,251}$")


def keyspace_name_issue(kind: str, name: Any) -> str | None:
    """The naming rule for a scope or collection (CAP-025 AC6); None when the name is valid.

    1–251 characters A-Z a-z 0-9 _ - %, not starting with _ or %. The only exception is the _default scope,
    which may be declared so that its collections are managed.
    """
    if kind == "scope" and name == "_default":
        return None
    text = str(name)
    if isinstance(name, str) and KEYSPACE_NAME.match(name) and name[0] not in "_%":
        return None
    shown = text if len(text) <= 40 else f"{text[:40]}… ({len(text)} characters)"
    rule = "1–251 characters of A-Z a-z 0-9 _ - %, not starting with _ or %"
    if kind == "scope":
        rule += " (_default is the only exception)"
    return f"{kind} name '{shown}' is not valid: use {rule}"


def parse_rfc3339(value: Any) -> datetime | None:
    """Aware datetime for an RFC 3339 time; None when it is not one."""
    if not isinstance(value, str) or not RFC3339.match(value.strip()):
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None


def _check_cidrs(cl: dict[str, Any], cp: tuple[Any, ...], add: Any, dupes: Any) -> None:
    """Allowed CIDRs (CAP-022 AC2/AC5): network addresses, no duplicates, 0.0.0.0/0 only with allowAnyIp."""
    cidrs = cl.get("allowedCidrs") or []
    for i, c in enumerate(cidrs):
        raw = c.get("cidr", "")
        if "expiresAt" in c and parse_rfc3339(c["expiresAt"]) is None:
            add(cp + ("allowedCidrs", i, "expiresAt"), f"{c['expiresAt']} is not an RFC 3339 time (for example "
                                                       "2026-12-31T23:59:59Z)")
        try:
            canon = normalize_cidr(raw)
        except ValueError:
            try:
                net = ipaddress.ip_network(raw, strict=False)
                add(cp + ("allowedCidrs", i, "cidr"), f"{raw} is not a network address (did you mean {net}?)")
            except ValueError:
                add(cp + ("allowedCidrs", i, "cidr"), f"{raw} is not a valid CIDR")
            continue
        if canon in ("0.0.0.0/0", "::/0") and not cl.get("allowAnyIp"):
            add(cp + ("allowedCidrs", i, "cidr"), f"{raw} allows every IP address; set allowAnyIp: true on the cluster "
                                                  "to confirm", "safety")
    dupes(cidrs, "cidr", cp + ("allowedCidrs",), "allowed CIDR", normalize_cidr)


def _check_hibernation(cl: dict[str, Any], cp: tuple[Any, ...], add: Any) -> None:
    """On-window times: hour 0–23 (24:00 only as an end), minute 00 or 30, start before end (CAP-020 rules)."""
    hib = cl.get("hibernation")
    if not isinstance(hib, dict):
        return
    for day in DAY_KEYS:
        value = hib.get(day)
        if not isinstance(value, str) or value in ("on", "off") or "-" not in value:
            continue
        start, end = value.split("-", 1)
        problems = []
        for label, t in (("start", start), ("end", end)):
            h, _, m = t.partition(":")
            if not (h.isdigit() and m.isdigit()):
                continue
            if m not in ("00", "30"):
                problems.append(f"{label} minute must be 00 or 30 (got {t})")
            if int(h) > 23 and not (label == "end" and t == "24:00"):
                problems.append(f"{label} hour must be 00–23 (got {t})")
        if not problems and start >= end.replace("24:00", "99:99"):
            problems.append(f"the on-window must start before it ends (got {value})")
        for msg in problems:
            add(cp + ("hibernation", day), msg, "hibernation")
    if hib.get("ensure") == "absent":
        return
    if not hib.get("timezone"):
        add(cp + ("hibernation",), "timezone is required (for example US/Pacific)", "hibernation")
    from capellactl.resources.schedule import DAYS, day_value

    if all(day_value(hib, d) == "off" for d in DAYS):
        add(cp + ("hibernation",), "the cluster cannot be off every day of the week (Capella rule)", "hibernation")


def config_warnings(cfg: Config) -> list[str]:
    """Valid but probably unintended settings, printed by every command that loads the file."""
    from capellactl.config.loader import fmt_path

    out = []
    now = datetime.now(timezone.utc)
    for entry in cfg.projects():
        for ci, cl in enumerate(entry.clusters):
            for i, c in enumerate(cl.get("allowedCidrs") or []):
                t = parse_rfc3339(c.get("expiresAt"))
                if t is not None and t <= now:
                    path = entry.clusters_base + (ci, "allowedCidrs", i, "expiresAt")
                    line = cfg.line_of(path)
                    out.append(f"warning: {fmt_path(path)}: expiresAt is in the past; Capella will remove it"
                               + (f" (line {line})" if line else ""))
            for ui, u in enumerate(cl.get("databaseCredentials") or []):
                for ai, a in enumerate(u.get("access") or []):
                    if not (a.get("resources") or {}).get("buckets"):  # CAP-027 AC5
                        path = entry.clusters_base + (ci, "databaseCredentials", ui, "access", ai)
                        line = cfg.line_of(path)
                        out.append(f"warning: {fmt_path(path)}: grants access to ALL buckets"
                                   + (f" (line {line})" if line else ""))
    return out


def check_cross_references(cfg: Config) -> list[ConfigIssue]:
    from capellactl.config.loader import ConfigIssue, fmt_path

    issues: list[ConfigIssue] = []

    def add(path: tuple[Any, ...], msg: str, topic: str = "config") -> None:
        issues.append(ConfigIssue(fmt_path(path), msg, cfg.line_of(path), topic=topic))

    def dupes(items: list[dict[str, Any]], key: str, base: tuple[Any, ...], label: str, norm: Any = None) -> None:
        seen: dict[str, int] = {}
        for i, it in enumerate(items):
            raw = it.get(key)
            if raw is None:
                continue
            try:
                k = norm(raw) if norm else str(raw)
            except ValueError:
                continue
            if k in seen:
                add(base + (i, key), f"duplicate {label} name '{raw}' (also at index {seen[k]})")
            else:
                seen[k] = i

    entries = cfg.projects()
    if cfg.data.get("projects") is not None:
        dupes([e.data for e in entries if not e.data.get("id")], "name", ("projects",), "project")
    free = [(e, i) for e in entries for i, c in enumerate(e.clusters) if c.get("tier") == "free"]
    for e, i in free[1:]:
        add(e.clusters_base + (i, "tier"), "only one free-tier cluster is allowed per organization", "config")
    for entry in entries:
        _check_project(cfg, entry, add, dupes)
    return issues


def _check_project(cfg: Config, entry: Any, add: Any, dupes: Any) -> None:
    clusters = entry.clusters
    cb = entry.clusters_base
    # Clusters pinned with id: may share a name (Capella allows it); only unpinned duplicates are ambiguous.
    unpinned = [(i, c) for i, c in enumerate(clusters) if not c.get("id")]
    seen: dict[str, int] = {}
    for i, c in unpinned:
        n = str(c.get("name"))
        if n in seen:
            add(cb + (i, "name"), f"duplicate cluster name '{n}' (also at index {seen[n]})")
        else:
            seen[n] = i

    # Cluster networks: valid network addresses that do not overlap other clusters of the project.
    nets: list[tuple[int, Any]] = []
    for ci, cl in enumerate(clusters):
        raw = (cl.get("cloudProvider") or {}).get("cidr")
        if not raw:
            continue
        path = cb + (ci, "cloudProvider", "cidr")
        try:
            net = ipaddress.ip_network(str(raw), strict=True)
        except ValueError:
            try:
                add(path, f"{raw} is not a network address (did you mean {ipaddress.ip_network(str(raw), strict=False)}?)")
            except ValueError:
                add(path, f"{raw} is not a valid CIDR")
            continue
        for oi, other in nets:
            if net.overlaps(other):
                add(path, f"{raw} overlaps the network of cluster '{clusters[oi].get('name')}' ({other})")
                break
        nets.append((ci, net))

    for ci, cl in enumerate(clusters):
        cp = cb + (ci,)
        _check_cidrs(cl, cp, add, dupes)
        _check_hibernation(cl, cp, add)
        _check_region(cl, cp, add)
        if cl.get("tier") == "free":
            for f in FREE_TIER_FORBIDDEN:
                if f in cl:
                    add(cp + (f,), f"not available for free-tier clusters (they have 1 node with data, index, query "
                                   f"and search, and a fixed size); remove {f} or use tier: provisioned")
            prov = (cl.get("cloudProvider") or {}).get("type")
            region = (cl.get("cloudProvider") or {}).get("region")
            allowed = FREE_TIER_REGIONS.get(str(prov), [])
            if prov and region and region not in allowed:
                add(cp + ("cloudProvider", "region"),
                    f"free-tier clusters on {prov} are available in: {', '.join(allowed)}")
            buckets = cl.get("buckets") or []
            dupes(buckets, "name", cp + ("buckets",), "bucket")
            for bi, b in enumerate(buckets):
                for f in b:
                    if f not in FREE_TIER_BUCKET_FIELDS:
                        add(cp + ("buckets", bi, f), "not available for free-tier buckets (only memoryAllocationInMb "
                                                     "and enableCrossClusterVersioning can be set; Capella chooses the "
                                                     "rest)")
            continue
        missing = [f for f in PROVISIONED_REQUIRED if f not in cl]
        for f in missing:
            add(cp, f"missing required field '{f}'")
        if missing:
            continue
        provider = (cl.get("cloudProvider") or {}).get("type")
        single = cl.get("configurationType") == "singleNode"
        groups = cl.get("serviceGroups") or []

        # Service groups
        if groups and not any("data" in (g.get("services") or []) for g in groups):
            add(cp + ("serviceGroups",), "at least one service group must run the data service", "scaling")
        seen_keys: set[str] = set()
        for g in groups:
            key = ",".join(sorted(g.get("services") or []))
            if key in seen_keys:
                add(cp + ("serviceGroups",), f"two groups run {key}; each group needs a different set of services",
                    "scaling")
            seen_keys.add(key)
        total = 0
        for gi, g in enumerate(groups):
            gp = cp + ("serviceGroups", gi)
            n = g.get("numOfNodes")
            if isinstance(n, int):
                total += n
                if single:
                    if n != 1:
                        add(gp + ("numOfNodes",), "singleNode clusters have exactly 1 node; create a multiNode cluster to scale out", "scaling")
                elif gi == 0 and not 3 <= n <= 27:
                    add(gp + ("numOfNodes",), "must be between 3 and 27", "scaling")
                elif gi > 0 and not 2 <= n <= 24:
                    add(gp + ("numOfNodes",), "additional service groups allow 2–24 nodes", "scaling")
            disk_type = ((g.get("node") or {}).get("disk") or {}).get("type")
            if provider in DISK_TYPES and disk_type and disk_type not in DISK_TYPES[provider]:
                add(gp + ("node", "disk", "type"),
                    f"disk type {disk_type} is not valid for {provider} (use: {', '.join(sorted(DISK_TYPES[provider]))})")
            if provider in ("aws", "gcp") and disk_type and ((g.get("node") or {}).get("disk") or {}).get("storage") is None:
                add(gp + ("node", "disk", "storage"), f"storage is required for {provider} disks")
            if provider == "aws" and disk_type and ((g.get("node") or {}).get("disk") or {}).get("iops") is None:
                add(gp + ("node", "disk", "iops"), "iops is required for aws disks")
            if provider in ("aws", "gcp") and ((g.get("node") or {}).get("disk") or {}).get("autoExpansion") is not None:
                add(gp + ("node", "disk", "autoExpansion"), "autoExpansion is for azure disks only")
            if single and set(g.get("services") or []) - SINGLE_NODE_SERVICES:
                add(gp + ("services",), "singleNode clusters run only data, index, query and search")
        if not single and total > 27:
            add(cp + ("serviceGroups",), f"a cluster can have at most 27 nodes (declared {total})", "scaling")
        if single:
            if len(groups) > 1:
                add(cp + ("serviceGroups",), "singleNode clusters have exactly one service group", "scaling")
            if (cl.get("availability") or {}).get("type") == "multi":
                add(cp + ("availability", "type"), "singleNode clusters must use availability: single")
        zones = cl.get("zones") or []
        if zones and (cl.get("availability") or {}).get("type") == "multi":
            add(cp + ("zones",), "zones can only be set for availability: single")

        # Buckets, scopes, collections
        buckets = cl.get("buckets") or []
        dupes(buckets, "name", cp + ("buckets",), "bucket")
        defined: dict[str, dict[str, set[str]]] = {}
        for bi, b in enumerate(buckets):
            for field, msg in bucket_type_rules(b):
                add(cp + ("buckets", bi, field), msg)
            replicas = b.get("replicas")
            if single and replicas not in (None, 0):
                add(cp + ("buckets", bi, "replicas"), "single-node clusters only support replicas: 0 (there is no "
                                                      "second node to hold a copy)")
            elif not single and replicas == 0:
                add(cp + ("buckets", bi, "replicas"), "replicas: 0 is only for single-node clusters; use 1, 2 or 3")
            scopes = b.get("scopes") or []
            dupes(scopes, "name", cp + ("buckets", bi, "scopes"), "scope")
            defined[b["name"]] = {}
            for si, s in enumerate(scopes):
                if (issue := keyspace_name_issue("scope", s.get("name"))) is not None:
                    add(cp + ("buckets", bi, "scopes", si, "name"), issue)
                colls = s.get("collections") or []
                dupes(colls, "name", cp + ("buckets", bi, "scopes", si, "collections"), "collection")
                for ci, c in enumerate(colls):
                    if (issue := keyspace_name_issue("collection", c.get("name"))) is not None:
                        add(cp + ("buckets", bi, "scopes", si, "collections", ci, "name"), issue)
                defined[b["name"]][s["name"]] = {c["name"] for c in colls}

        # Database credentials
        creds = cl.get("databaseCredentials") or []
        dupes(creds, "name", cp + ("databaseCredentials",), "credential")
        for ui, u in enumerate(creds):
            password = u.get("password")
            if isinstance(password, str) and password and not meets_rules(password):  # CAP-028 AC3; value never shown
                add(cp + ("databaseCredentials", ui, "password"),
                    f"password for {u.get('name')} does not meet Capella rules ({RULES})", "credentials")
            for ai, a in enumerate(u.get("access") or []):
                for rbi, rb in enumerate(((a.get("resources") or {}).get("buckets")) or []):
                    rp = cp + ("databaseCredentials", ui, "access", ai, "resources", "buckets", rbi)
                    if rb.get("external"):
                        continue
                    bname = rb.get("name")
                    if bname == "*":  # Capella's wildcard (files written before sync dropped it)
                        continue
                    if bname not in defined:
                        add(rp + ("name",), f"bucket '{bname}' is not defined in cluster '{cl.get('name')}' "
                                            "(define it under buckets, or set external: true)", "credentials")
                        continue
                    for rsi, rs in enumerate(rb.get("scopes") or []):
                        sname = rs.get("name")
                        if sname == "*":
                            continue
                        if sname not in defined[bname] and sname != "_default":
                            add(rp + ("scopes", rsi, "name"), f"scope '{sname}' is not defined in bucket '{bname}'", "credentials")
                            continue
                        for rci, cname in enumerate(rs.get("collections") or []):
                            if sname != "_default" and cname != "*" and cname not in defined[bname].get(sname, set()):
                                add(rp + ("scopes", rsi, "collections", rci),
                                    f"collection '{cname}' is not defined in {bname}.{sname}", "credentials")
