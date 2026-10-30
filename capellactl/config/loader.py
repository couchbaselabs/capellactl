"""Load and validate capella.yaml (CAP-002).

Pipeline: YAML (with line numbers) → apiVersion check → secret references → schema → defaults →
cross-reference checks → Config model. Never touches the network.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from capellactl.output.notice import Notice
from capellactl.output.redact import redactor

API_VERSION = "capellactl/v1"
REF_RE = re.compile(r"\$\{(file:)?([^}]+)\}")
WHOLE_REF_RE = re.compile(r"^\$\{(file:)?([^}]+)\}$")
DAY_KEYS = ("weekdays", "weekend", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

PathT = tuple[Any, ...]


def fmt_path(path: PathT) -> str:
    out = ""
    for p in path:
        if isinstance(p, int):
            out += f"[{p}]"
        else:
            out += ("." if out else "") + str(p)
    return out or "(root)"


def parse_path(text: str) -> PathT:
    """`projects[1].clusters[0].name` → ("projects", 1, "clusters", 0, "name"); the inverse of fmt_path."""
    return tuple(int(i) if i else k for i, k in re.findall(r"\[(\d+)\]|([^.\[\]]+)", text))


# List keys whose entries are named resources (CAP-062): the label shown and the field that names an entry.
NAMED_LISTS = {"projects": ("project", "name"), "clusters": ("cluster", "name"), "serviceGroups": ("service group", "services"),
               "buckets": ("bucket", "name"), "scopes": ("scope", "name"), "collections": ("collection", "name"),
               "databaseCredentials": ("credential", "name"), "allowedCidrs": ("allowed IP range", "cidr")}


def describe(data: Any, path: PathT) -> str:
    """Where a problem is, by name: `project shop › cluster web-01 › service group data › numOfNodes` (CAP-062 AC1).

    Named resources are followed while each one sits directly in the one before it; the rest is the field path."""
    parts: list[str] = []
    if path[:1] == ("clusters",) and isinstance(data, dict) and isinstance(data.get("project"), dict):
        parts.append(f"project {data['project'].get('name')}")  # the single-project form
    node, i = data, 0
    while i + 1 < len(path) and path[i] in NAMED_LISTS and isinstance(path[i + 1], int):
        label, key = NAMED_LISTS[path[i]]
        items = node.get(path[i]) if isinstance(node, dict) else None
        item = items[path[i + 1]] if isinstance(items, list) and path[i + 1] < len(items) else None
        name = item.get(key) if isinstance(item, dict) else None
        if isinstance(name, list):
            name = ",".join(sorted(str(s) for s in name))
        if isinstance(name, str) and len(name) > 40:
            name = name[:40] + "…"  # a name that is itself the problem (too long) would fill the line
        parts.append(f"{label} {name}" if name not in (None, "") else f"{label} #{path[i + 1] + 1}")
        node, i = item, i + 2
    rest = path[i:]
    if parts and rest == (NAMED_LISTS[path[i - 2]][1],):
        rest = ()  # the field that names the entry is the entry itself
    return " › ".join(parts + ([fmt_path(rest)] if rest or not parts else []))


@dataclass
class ConfigIssue:
    path: str
    message: str
    line: int | None = None
    topic: str = "config"
    fix: str = ""
    where: str = ""

    def __str__(self) -> str:
        """`where (line N)`, then the problem and its next step (`action:`) indented under it (CAP-062, CAP-063)."""
        out = f"{self.where or self.path}{f' (line {self.line})' if self.line else ''}\n  {self.message}"
        return out + (f"\n  action: {self.fix}" if self.fix else "")


def render_issues(heading: str, issues: list[ConfigIssue]) -> str:
    """A heading, then one indented block per problem."""
    return "\n".join([heading, *("  " + str(i).replace("\n", "\n  ") for i in issues)])


FIX_PROBLEMS = "Fix each problem above (an 'action:' line says how), then run the command again."


def count_problems(n: int) -> str:
    return f"{n} problem{'' if n == 1 else 's'}"


class ConfigError(Exception):
    def __init__(self, issues: list[ConfigIssue], source: str = "capella.yaml") -> None:
        self.issues = sorted(issues, key=lambda i: (i.line or 0, i.path))
        self.source = source
        super().__init__(render_issues(f"{source} has {count_problems(len(self.issues))}:", self.issues))


def _raise(issues: list[ConfigIssue], data: Any, source: str) -> None:
    for i in issues:
        i.where = i.where or describe(data, parse_path(i.path))
    raise ConfigError(issues, source)


@dataclass
class ProjectEntry:
    """One project of the file, with the YAML paths of the project and of its clusters list."""

    data: dict[str, Any]
    clusters: list[dict[str, Any]]
    base: PathT
    clusters_base: PathT

    @property
    def name(self) -> str:
        return str(self.data.get("name"))


def project_entries(data: dict[str, Any]) -> list[ProjectEntry]:
    """Both forms: `projects: [...]` (each with clusters) or single-project `project:` + `clusters:`."""
    if isinstance(data.get("projects"), list):
        return [ProjectEntry(p, p.get("clusters") or [], ("projects", i), ("projects", i, "clusters"))
                for i, p in enumerate(data["projects"]) if isinstance(p, dict)]
    if isinstance(data.get("project"), dict):
        return [ProjectEntry(data["project"], data.get("clusters") or [], ("project",), ("clusters",))]
    return []


@dataclass
class Config:
    path: Path
    data: dict[str, Any]
    lines: dict[PathT, int]
    organization_id: str | None
    hints: list[str] = field(default_factory=list)
    warnings: list[Notice] = field(default_factory=list)

    def projects(self) -> list[ProjectEntry]:
        return project_entries(self.data)

    @property
    def project(self) -> dict[str, Any]:
        """The first project (convenience for single-project files)."""
        entries = self.projects()
        return entries[0].data if entries else {}

    @property
    def clusters(self) -> list[dict[str, Any]]:
        """Every cluster of every project."""
        return [c for e in self.projects() for c in e.clusters]

    def project_names(self) -> list[str]:
        return [e.name for e in self.projects()]

    @property
    def credentials_output(self) -> str:
        return str(self.data.get("credentialsOutput") or "./.capellactl/credentials")

    def counts(self) -> dict[str, int]:
        c = {"project": len(self.projects()), "cluster": 0, "bucket": 0, "scope": 0, "collection": 0, "credential": 0,
             "allowed CIDR": 0, "hibernation schedule": 0}
        for cl in self.clusters:
            c["cluster"] += 1
            c["allowed CIDR"] += len(cl.get("allowedCidrs") or [])
            c["credential"] += len(cl.get("databaseCredentials") or [])
            hib = cl.get("hibernation")
            if hib and hib.get("ensure", "present") != "absent":
                c["hibernation schedule"] += 1
            for b in cl.get("buckets") or []:
                c["bucket"] += 1
                for s in b.get("scopes") or []:
                    c["scope"] += 1
                    c["collection"] += len(s.get("collections") or [])
        return c

    def summary(self) -> str:
        def plural(n: int, word: str) -> str:
            if n == 1:
                return f"{n} {word}"
            if word == "allowed CIDR":
                return f"{n} allowed CIDRs"
            if word == "hibernation schedule":
                return f"{n} hibernation schedules"
            return f"{n} {word}s"

        c = self.counts()
        order = ["project", "cluster", "bucket", "scope", "collection", "credential", "allowed CIDR", "hibernation schedule"]
        return "Configuration valid: " + ", ".join(plural(c[k], k) for k in order)

    def line_of(self, path: PathT) -> int | None:
        while path:
            if path in self.lines:
                return self.lines[path]
            path = path[:-1]
        return None


# ---------------------------------------------------------------- YAML + lines
def _load_yaml(text: str) -> tuple[Any, dict[PathT, int]]:
    loader = yaml.SafeLoader(text)
    try:
        node = loader.get_single_node()
        data = loader.construct_document(node) if node is not None else None
    finally:
        loader.dispose()
    lines: dict[PathT, int] = {}

    def walk(n: yaml.Node, path: PathT) -> None:
        lines[path] = n.start_mark.line + 1
        if isinstance(n, yaml.MappingNode):
            for k, v in n.value:
                key = k.value
                lines[path + (key,)] = k.start_mark.line + 1
                walk(v, path + (key,))
                lines[path + (key,)] = k.start_mark.line + 1
        elif isinstance(n, yaml.SequenceNode):
            for i, v in enumerate(n.value):
                walk(v, path + (i,))

    if node is not None:
        walk(node, ())
    return data, lines


def _iter_strings(obj: Any, path: PathT = ()) -> Iterator[tuple[PathT, str]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_strings(v, path + (i,))
    elif isinstance(obj, str):
        yield path, obj


def _set(obj: Any, path: PathT, value: Any) -> None:
    for p in path[:-1]:
        obj = obj[p]
    obj[path[-1]] = value


def _is_password(path: PathT) -> bool:
    return bool(path) and path[-1] == "password"


# ------------------------------------------------------------------ secrets
def _resolve_secrets(data: Any, base_dir: Path, lines: dict[PathT, int], env: dict[str, str]) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []

    def line(p: PathT) -> int | None:
        return lines.get(p)

    for path, value in list(_iter_strings(data)):
        if _is_password(path) and not WHOLE_REF_RE.match(value.strip()):
            issues.append(ConfigIssue(fmt_path(path), "passwords must be supplied via ${VAR} or ${file:...}",
                                      line(path), topic="credentials"))
            _set(data, path, None)
            continue
        if "${" not in value:
            continue

        missing: list[str] = []

        def sub(m: re.Match[str], _missing: list[str] = missing) -> str:
            is_file, ref = m.group(1), m.group(2).strip()
            if is_file:
                p = (base_dir / ref) if not Path(ref).is_absolute() else Path(ref)
                try:
                    return p.read_text(encoding="utf-8").rstrip("\r\n")
                except OSError:
                    _missing.append(f"file {ref} not found (resolved to {p})")
                    return ""
            if ref not in env:
                _missing.append(f"environment variable {ref} is not set")
                return ""
            return env[ref]

        resolved = REF_RE.sub(sub, value)
        if missing:
            if path == ("organizationId",):
                # May be supplied by a profile or CAPELLA_ORG_ID at run time (CAP-037 precedence).
                data.pop("organizationId", None)
                continue
            for msg in missing:
                issues.append(ConfigIssue(fmt_path(path), msg, line(path), topic="config"))
            continue
        if _is_password(path):
            redactor.register(resolved)
        _set(data, path, resolved)
    return issues


# ------------------------------------------------------------------- schema
_SCHEMA: dict[str, Any] | None = None


def load_schema() -> dict[str, Any]:
    global _SCHEMA
    if _SCHEMA is None:
        text = resources.files("capellactl.config").joinpath("schema.json").read_text(encoding="utf-8")
        _SCHEMA = json.loads(text)
    return _SCHEMA


def _schema_message(err: ValidationError) -> tuple[PathT, str]:
    path: PathT = tuple(err.absolute_path)
    v, s = err.validator, err.schema if isinstance(err.schema, dict) else {}
    if v == "required":
        missing = re.findall(r"'([^']+)' is a required property", err.message)
        return path, f"missing required field '{missing[0] if missing else err.message}'"
    if v == "additionalProperties":
        extras = re.findall(r"'([^']+)'", err.message.split("(")[-1])
        allowed = list((s.get("properties") or {}).keys())
        msgs = []
        for x in extras:
            close = difflib.get_close_matches(x, allowed, n=1)
            msgs.append(f"unknown field '{x}'" + (f" (did you mean '{close[0]}'?)" if close else ""))
        return path + ((extras[0],) if len(extras) == 1 else ()), "; ".join(msgs)
    if v in ("minLength", "maxLength"):
        n = err.validator_value
        if v == "minLength":
            return path, "must not be empty" if n == 1 else f"must be at least {n} characters"
        return path, f"must be at most {n} characters"
    if v in ("minimum", "maximum"):
        lo, hi = s.get("minimum"), s.get("maximum")
        if lo is not None and hi is not None:
            return path, f"must be between {lo} and {hi}"
        return path, f"must be >= {lo}" if v == "minimum" else f"must be <= {hi}"
    if v == "enum" and "databaseCredentials" in path and "privileges" in path:
        return path, "basic credentials support read/write only; advanced credentials are planned for 1.1"
    if v == "enum":
        return path, "must be one of: " + ", ".join(str(x) for x in s.get("enum", []))
    if v == "type":
        return path, f"must be a{'n' if str(err.validator_value)[0] in 'aeiou' else ''} {err.validator_value}"
    if v == "const":
        return path, f"must be {err.validator_value}"
    if v == "oneOf" and path and path[-1] in DAY_KEYS:
        return path, "must be 'on', 'off' or an on-window 'HH:MM-HH:MM'"
    if v == "oneOf" and not path:
        inst = err.instance if isinstance(err.instance, dict) else {}
        if "projects" in inst:
            return path, "use either projects: or the single-project project:/clusters:, not both"
        return path, "missing 'projects' (or the single-project 'project')"
    return path, err.message


def _validate_schema(data: Any, lines: dict[PathT, int]) -> list[ConfigIssue]:
    validator = Draft202012Validator(load_schema())
    issues = []
    for err in validator.iter_errors(data):
        path, msg = _schema_message(err)
        topic = "hibernation" if "hibernation" in path else "config"
        issues.append(ConfigIssue(fmt_path(path), msg, _line(lines, path), topic=topic))
    return issues


def _line(lines: dict[PathT, int], path: PathT) -> int | None:
    while True:
        if path in lines:
            return lines[path]
        if not path:
            return None
        path = path[:-1]


# ------------------------------------------------------------------ defaults
BUCKET_DEFAULTS = {
    "type": "couchbase",
    "replicas": 1,
    "durabilityLevel": "none",
    "timeToLiveInSeconds": 0,
    "flushEnabled": False,
    "bucketConflictResolution": "seqno",
}


def _all_clusters(data: dict[str, Any]) -> list[dict[str, Any]]:
    entries = project_entries(data)
    clusters = [c for e in entries for c in e.clusters] if entries else list(data.get("clusters") or [])
    return [c for c in clusters if isinstance(c, dict)]


def apply_defaults(data: dict[str, Any]) -> None:
    for cl in _all_clusters(data):
        if cl.get("tier") == "free":  # free-tier clusters and their buckets have a fixed shape
            continue
        cl.setdefault("configurationType", "multiNode")
        single = cl["configurationType"] == "singleNode"
        for b in cl.get("buckets") or []:
            for k, v in BUCKET_DEFAULTS.items():
                # Capella accepts only 0 replicas on single-node clusters: there is no second node for a copy.
                b.setdefault(k, 0 if single and k == "replicas" else v)


def _normalize_hibernation_booleans(data: dict[str, Any], hints: list[str]) -> None:
    """YAML 1.1 reads unquoted on/off as booleans; in schedule day keys they mean 'on'/'off' (CAP-020 AC10)."""
    for cl in _all_clusters(data):
        hib = cl.get("hibernation")
        if not isinstance(hib, dict):
            continue
        for k in DAY_KEYS:
            if isinstance(hib.get(k), bool):
                hib[k] = "on" if hib[k] else "off"
                tip = 'tip: quote "on"/"off" in hibernation to avoid YAML boolean conversion'
                if tip not in hints:
                    hints.append(tip)


# ---------------------------------------------------------------- public API
def declared_org_id(path: str | Path, env: dict[str, str]) -> str | None:
    """The file's organizationId, with ${VAR} references resolved; None when absent, unreadable or unresolved
    (the organization then comes from the profile, CAP-037). Never loads secrets (CAP-047)."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    value = data.get("organizationId") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    unresolved: list[str] = []

    def sub(m: re.Match[str]) -> str:
        ref = m.group(2).strip()
        if m.group(1) or ref not in env:
            unresolved.append(ref)
            return ""
        return env[ref]

    resolved = REF_RE.sub(sub, value).strip()
    return None if unresolved or not resolved else resolved


def load_config(path: str | Path, env: dict[str, str] | None = None) -> Config:
    """Load, resolve, validate and default a capella.yaml file. Raises ConfigError (exit 3)."""
    p = Path(path)
    env = dict(os.environ) if env is None else env
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError([ConfigIssue(str(p), "file not found; run 'capellactl sync' to write it from your Capella project")],
                          p.name) from None
    try:
        data, lines = _load_yaml(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise ConfigError([ConfigIssue(str(p), f"invalid YAML: {getattr(exc, 'problem', exc)}",
                                       (mark.line + 1) if mark else None)], p.name) from None
    if not isinstance(data, dict):
        raise ConfigError([ConfigIssue(str(p), "the file must be a YAML mapping")], p.name)

    version = data.get("apiVersion")
    if version != API_VERSION:
        if isinstance(version, str) and version.startswith("capellactl/"):
            raise ConfigError([ConfigIssue("apiVersion", f"this file needs capellactl supporting {version}; installed version "
                                                         f"supports {API_VERSION}", lines.get(("apiVersion",)))], p.name)
        raise ConfigError([ConfigIssue("apiVersion", f"must be {API_VERSION}", lines.get(("apiVersion",), 1))], p.name)

    hints: list[str] = []
    issues = _resolve_secrets(data, p.parent, lines, env)
    _normalize_hibernation_booleans(data, hints)
    issues += _validate_schema(data, lines)
    if issues:
        _raise(issues, data, p.name)

    apply_defaults(data)

    from capellactl.config.crossref import check_cross_references, config_warnings

    cfg = Config(path=p, data=data, lines=lines, organization_id=data.get("organizationId") or None, hints=hints)
    issues = check_cross_references(cfg)
    if issues:
        _raise(issues, data, p.name)
    cfg.warnings = config_warnings(cfg)
    return cfg
