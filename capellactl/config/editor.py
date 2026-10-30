"""Comment-preserving edits to capella.yaml (CAP-038).

capella.yaml is owned by capellactl: commands change it, users do not have to. Edits go through
ruamel.yaml's round-trip mode so the comments written by `import` (password notes, advanced-credential
blocks) and the compact one-line style are kept.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from capellactl.engine.normalize import group_key
from capellactl.importer import FLOW_KEYS, NEW_CLUSTER_TEMPLATE


def _yaml() -> YAML:
    y = YAML()
    y.indent(mapping=2, sequence=4, offset=2)
    y.preserve_quotes = True
    y.width = 120
    return y


def to_commented(obj: Any, key: str | None = None) -> Any:
    """Plain data → ruamel nodes, with small leaf values in one-line flow style (like `import`)."""
    if isinstance(obj, dict):
        m = CommentedMap()
        for k, v in obj.items():
            m[k] = to_commented(v, k)
        if key in FLOW_KEYS and all(not isinstance(v, (dict, list)) for v in obj.values()):
            m.fa.set_flow_style()
        return m
    if isinstance(obj, list):
        s = CommentedSeq(to_commented(v) for v in obj)
        if all(not isinstance(v, (dict, list)) for v in obj) and (key in FLOW_KEYS or key == "collections"):
            s.fa.set_flow_style()
        return s
    return obj


# Key order of a cluster, as import writes it; new keys are inserted in this order, not appended at the end.
CLUSTER_KEY_ORDER = ("id", "name", "description", "configurationType", "cloudProvider", "couchbaseServer",
                     "availability", "support", "serviceGroups", "cmekId", "enablePrivateDNSResolution",
                     "deletionProtection", "allowAnyIp", "hibernation", "backupSchedule", "allowedCidrs", "buckets",
                     "databaseCredentials")
# A bucket's backup schedule goes before its scopes (as sync writes it).
BUCKET_KEY_ORDER = ("backupSchedule", "scopes")


def put(node: CommentedMap, key: str, value: Any, order: tuple[str, ...] = CLUSTER_KEY_ORDER) -> None:
    """Set `key`; a new key goes before the first existing key that `order` places after it (else at the end)."""
    if key in node or key not in order:
        node[key] = value
        return
    later = set(order[order.index(key) + 1:])
    pos = next((i for i, k in enumerate(node.keys()) if k in later), len(node))
    node.insert(pos, key, value)


class ConfigEditor:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.original = path.read_text(encoding="utf-8")
        self._yaml = _yaml()
        self.doc: CommentedMap = self._yaml.load(self.original.replace(NEW_CLUSTER_TEMPLATE, ""))
        self.converted = False

    # ------------------------------------------------------------ projects
    def ensure_projects(self) -> CommentedSeq:
        """Convert the single-project form (project: + clusters:) to projects: in place (CAP-040 AC2)."""
        if "projects" in self.doc:
            return self.doc["projects"]  # type: ignore[no-any-return]
        old_project = self.doc.get("project") or CommentedMap()
        project = CommentedMap(old_project)
        clusters = self.doc.get("clusters")
        project["clusters"] = clusters if isinstance(clusters, CommentedSeq) else CommentedSeq()
        new = CommentedMap()
        for k, v in self.doc.items():
            if k == "project":
                new["projects"] = CommentedSeq([project])
            elif k != "clusters":
                new[k] = v
        if "projects" not in new:
            new["projects"] = CommentedSeq([project])
        if self.doc.ca.comment:
            new.ca.comment = self.doc.ca.comment
        self.doc = new
        self.converted = True
        return self.doc["projects"]  # type: ignore[no-any-return]

    def project_names(self) -> list[str]:
        if "projects" in self.doc:
            return [str(p.get("name")) for p in self.doc["projects"] or []]
        return [str((self.doc.get("project") or {}).get("name"))] if self.doc.get("project") else []

    def find_project(self, name: str) -> CommentedMap | None:
        for p in self.ensure_projects():
            if isinstance(p, CommentedMap) and p.get("name") == name:
                return p
        return None

    def add_project(self, node: Any) -> None:
        self.ensure_projects().append(node if isinstance(node, CommentedMap) else to_commented(node))

    # ------------------------------------------------------------ clusters
    def clusters(self, project: CommentedMap) -> CommentedSeq:
        seq = project.get("clusters")
        if not isinstance(seq, CommentedSeq) or len(seq) == 0:
            seq = CommentedSeq()
            project["clusters"] = seq
        return seq

    def find_cluster(self, name: str, project: str | None = None) -> tuple[CommentedMap, CommentedMap] | None:
        """(project, cluster) for a cluster name; LookupError when the name is used in several projects."""
        found = []
        for p in self.ensure_projects():
            if project and p.get("name") != project:
                continue
            for c in p.get("clusters") or []:
                if isinstance(c, CommentedMap) and c.get("name") == name:
                    found.append((p, c))
        if len(found) > 1:
            names = ", ".join(str(p.get("name")) for p, _ in found)
            raise LookupError(f"cluster {name} is in several projects ({names}); pass --project NAME")
        return found[0] if found else None

    def remove_cluster(self, name: str, project: CommentedMap) -> None:
        seq = self.clusters(project)
        for i, c in enumerate(seq):
            if isinstance(c, CommentedMap) and c.get("name") == name:
                del seq[i]
                return

    def group(self, cluster: CommentedMap, services: str | None) -> CommentedMap:
        """The service group named by `services` (e.g. 'data,index,query'), or the one running data."""
        groups = cluster.get("serviceGroups") or []
        if services:
            key = ",".join(sorted(s.strip() for s in services.split(",") if s.strip()))
            found = [g for g in groups if group_key(g) == key]
            if not found:
                raise LookupError(f"no service group '{key}' (groups: {', '.join(group_key(g) for g in groups)})")
            return found[0]  # type: ignore[no-any-return,unused-ignore]
        data = [g for g in groups if "data" in (g.get("services") or [])]
        if len(data) != 1:
            raise LookupError("more than one group runs data")
        return data[0]  # type: ignore[no-any-return,unused-ignore]

    # ------------------------------------------------------------ changes
    def add_cluster(self, project: CommentedMap, cluster: dict[str, Any]) -> None:
        self.clusters(project).append(to_commented(cluster))

    def set_path(self, node: CommentedMap, path: list[str], value: Any) -> None:
        for k in path[:-1]:
            if k not in node or node[k] is None:
                put(node, k, to_commented({}, k))
            node = node[k]
        put(node, path[-1], value)

    # ------------------------------------------------------------ output
    def text(self) -> str:
        buf = io.StringIO()
        self._yaml.dump(self.doc, buf)
        return buf.getvalue()

    def save(self, text: str | None = None) -> Path:
        """Write the file, keeping the previous version as <name>.bak. Returns the backup path."""
        backup = self.path.with_name(self.path.name + ".bak")
        backup.write_text(self.original, encoding="utf-8")
        self.path.write_text(text if text is not None else self.text(), encoding="utf-8")
        self.original = self.path.read_text(encoding="utf-8")
        return backup
