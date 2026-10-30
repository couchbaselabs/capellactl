"""In-memory fake of the Capella Management API v4.0 (CAP-004).

Install it into a `responses.RequestsMock`; every request from capellactl is served from state held
here. Behaviour mirrors the OpenAPI spec: 202 + currentState progression for clusters, 201 creates,
204 updates, ETag/If-Match/412, 409 code 1010 for duplicates, 404 after delete, base64 bucket IDs,
generated credential passwords returned only on create, onOffSchedule 404 when none, /stats memory.
Backups (CAP-056–CAP-059): cloud snapshot schedule (204 when none) checked against the plan's options, snapshots and
restores that complete after `step_seconds`, bucket backup schedules (404 when none), backups grouped in cycles,
on-demand bucket backups (202 without a body), restores and exports.
"""

from __future__ import annotations

import base64
import copy
import fnmatch
import itertools
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import responses

from capellactl import DEFAULT_BASE_URL
from capellactl.engine.clock import FakeClock
from capellactl.output.redact import redact_obj

Resp = tuple[int, dict[str, str], str]


@dataclass
class Call:
    method: str
    path: str
    body: Any
    headers: dict[str, str]
    query: dict[str, list[str]] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"Call({self.method} {self.path} body={redact_obj(self.body)!r})"


@dataclass
class _Fault:
    method: str
    glob: str
    status: int | None
    code: int | None
    times: int
    headers: dict[str, str]
    exc: BaseException | None
    before: Callable[[], None] | None = None


def bucket_id(name: str) -> str:
    return base64.b64encode(name.encode()).decode().rstrip("=")


def _err(status: int, message: str, code: int | None = None, hint: str = "") -> Resp:
    body = {"httpStatusCode": status, "code": code if code is not None else status * 10, "message": message,
            "hint": hint or message}
    return status, {"Content-Type": "application/json"}, json.dumps(body)


def _ok(status: int, body: Any = None, headers: dict[str, str] | None = None) -> Resp:
    h = {"Content-Type": "application/json", **(headers or {})}
    return status, h, "" if body is None else json.dumps(body)


DEFAULT_CLUSTER = {
    "description": "",
    "configurationType": "multiNode",
    "cloudProvider": {"type": "aws", "region": "us-east-1", "cidr": "10.10.0.0/24"},
    "couchbaseServer": {"version": "8.0.1"},
    "serviceGroups": [{"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
                       "numOfNodes": 3, "services": ["data", "index", "query"]}],
    "availability": {"type": "multi"},
    "support": {"plan": "developer pro", "timezone": "PT"},
}


# Azure premium disks: size (GB) and IOPS are set by the type; Capella reports them on GET.
AZURE_FIXED_DISKS = {"P6": (64, 240), "P10": (128, 500), "P15": (256, 1100), "P20": (512, 2300),
                     "P30": (1024, 5000), "P40": (2048, 7500), "P50": (4096, 7500), "P60": (8192, 16000)}


def audit(version: int = 1) -> dict[str, Any]:
    """The audit block Capella returns on organizations, projects, clusters, credentials and allowed CIDRs."""
    return {"createdBy": "fake-api-key", "createdAt": "2026-01-01T00:00:00Z", "modifiedBy": "fake-api-key",
            "modifiedAt": "2026-01-01T00:00:00Z", "version": version}


class FakeCapella:
    def __init__(self, org_id: str = "org-1", clock: FakeClock | None = None, base_url: str = DEFAULT_BASE_URL,
                 step_seconds: float = 60.0) -> None:
        self.org_id = org_id
        self.clock = clock or FakeClock()
        self.base_url = base_url.rstrip("/")
        self.step_seconds = step_seconds
        self.orgs: dict[str, dict[str, Any]] = {org_id: {"id": org_id, "name": "Nova Corp", "description": "",
                                                         "preferences": {"sessionDuration": 7200},
                                                         "audit": audit()}}
        self.projects: dict[str, dict[str, Any]] = {}
        self.clusters: dict[str, dict[str, Any]] = {}
        self.cidrs: dict[str, dict[str, Any]] = {}
        self.buckets: dict[tuple[str, str], dict[str, Any]] = {}
        self.scopes: dict[tuple[str, str], dict[str, dict[str, dict[str, Any]]]] = {}
        self.users: dict[str, dict[str, Any]] = {}
        self.schedules: dict[str, dict[str, Any]] = {}
        # Backups (CAP-056–CAP-059)
        self.snapshot_schedules: dict[str, dict[str, Any]] = {}
        self.snapshot_options = {"intervals": [1, 2, 4, 6, 8, 12, 24], "minimumRetention": 24, "maximumRetention": 2160}
        self.snapshot_regions = ["us-east-2", "us-west-2", "eu-west-1"]
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.snapshot_restores: dict[str, dict[str, Any]] = {}
        self.bucket_backup_schedules: dict[tuple[str, str], dict[str, Any]] = {}
        self.backups: dict[str, dict[str, Any]] = {}
        self.exports: dict[str, dict[str, Any]] = {}
        self.bucket_restores: list[dict[str, Any]] = []
        self.backup_fails_next = False  # the next on-demand bucket backup ends in status failed
        self.versions: dict[str, int] = {}
        self.cluster_total_memory_mb = 20480
        # Capella's answer to a second POST of the same CIDR is unconfirmed (CAP-022 open question): 409 by default.
        self.cidr_duplicates_allowed = False
        self.api_keys: set[str] | None = None  # None: accept any bearer token
        self._calls: list[Call] = []
        self._faults: list[_Fault] = []
        self.fail_deploy_next = False  # the next cluster create ends in deploymentFailed (accepted, then fails)
        # Called as hook(method, path) before each request is served; may raise to simulate failures.
        self.hooks: list[Callable[[str, str], None]] = []
        self._ids = itertools.count(1)
        self._routes: list[tuple[str, re.Pattern[str], Callable[..., Resp]]] = []
        self._build_routes()

    # ------------------------------------------------------------ install
    def install(self, rsps: responses.RequestsMock) -> None:
        pattern = re.compile(re.escape(self.base_url) + r"/v4(/.*)?(\?.*)?$")
        for method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            rsps.add_callback(method, pattern, callback=self._dispatch)

    # ------------------------------------------------------------ seeding
    def _new_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids)}"

    def _bump(self, key: str) -> str:
        self.versions[key] = self.versions.get(key, 0) + 1
        return str(self.versions[key])

    def seed_project(self, name: str, **fields: Any) -> str:
        pid = fields.pop("id", None) or self._new_id("p")
        self.projects[pid] = {"id": pid, "name": name, "description": fields.pop("description", ""),
                              "audit": audit(), **fields}
        self._bump(f"project:{pid}")
        return str(pid)

    def seed_cluster(self, project_id: str, name: str, state: str = "healthy", **fields: Any) -> str:
        cid = fields.pop("id", None) or self._new_id("c")
        body = copy.deepcopy(DEFAULT_CLUSTER)
        if "cloudProvider" not in fields:
            # Capella requires clusters in a project to use non-overlapping networks.
            used = {(c["body"].get("cloudProvider") or {}).get("cidr") for c in self.clusters.values()}
            n = 10
            while f"10.{n}.0.0/24" in used:
                n += 1
            body["cloudProvider"]["cidr"] = f"10.{n}.0.0/24"
        body.update(copy.deepcopy(fields))
        body.update({"id": cid, "name": name, "connectionString": f"couchbases://cb.{cid}.cloud.couchbase.com",
                     "deletionProtection": body.get("deletionProtection", False), "expressScaling": "disabled",
                     "audit": audit()})
        self.clusters[cid] = {"body": body, "project": project_id, "seq": [(state, -1.0)], "deleted_at": None,
                              "destroy_fails": False}
        self._bump(f"cluster:{cid}")
        return str(cid)

    def seed_free_cluster(self, project_id: str, name: str, state: str = "healthy", **fields: Any) -> str:
        """A free-tier cluster as Capella reports it: 1 node, data/index/query/search, support plan free."""
        free = {"configurationType": "singleNode", "availability": {"type": "single"},
                "support": {"plan": "free", "timezone": "PT"},
                "serviceGroups": [{"node": {"compute": {"cpu": 2, "ram": 8},
                                            "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
                                   "numOfNodes": 1, "services": ["data", "index", "query", "search"]}]}
        cid = self.seed_cluster(project_id, name, state, **{**free, **fields})
        for key in ("deletionProtection", "expressScaling"):  # not in the free-tier cluster response
            self.clusters[cid]["body"].pop(key, None)
        return cid

    def seed_bucket(self, cluster_id: str, name: str, **fields: Any) -> str:
        bid = bucket_id(name)
        self.buckets[(cluster_id, bid)] = {"id": bid, "name": name, "type": "couchbase", "storageBackend": "couchstore",
                                           "memoryAllocationInMb": 100, "bucketConflictResolution": "seqno",
                                           "durabilityLevel": "none", "replicas": 1, "flushEnabled": False,
                                           "timeToLiveInSeconds": 0, "evictionPolicy": "fullEviction", "priority": 0,
                                           "enableCrossClusterVersioning": False,
                                           "stats": {"itemCount": 0, "opsPerSecond": 0, "diskUsedInMib": 0,
                                                     "memoryUsedInMib": 0},
                                           **fields}
        self.scopes[(cluster_id, bid)] = {"_default": {"_default": {"name": "_default", "maxTTL": 0}}, "_system": {}}
        return bid

    def seed_scope(self, cluster_id: str, bucket: str, scope: str, collections: dict[str, int] | None = None) -> None:
        """A scope (and its collections, name → maxTTL) in an existing bucket, as Capella stores it."""
        cols = self.scopes[(cluster_id, bucket_id(bucket))].setdefault(scope, {})
        for name, ttl in (collections or {}).items():
            cols[name] = {"name": name, "maxTTL": ttl}
            self.versions[f"collection:{cluster_id}/{bucket_id(bucket)}/{scope}/{name}"] = 1

    def seed_snapshot(self, cluster_id: str, created_at: str = "2026-10-28T02:00:00Z", retention: int = 720,
                      type_: str = "scheduled", status: str = "complete", **fields: Any) -> str:
        """A cloud snapshot backup of a cluster (done unless `status` says otherwise)."""
        sid = fields.pop("id", None) or self._new_id("snap")
        project = self.clusters[cluster_id]["project"]
        self.snapshots[sid] = {"id": sid, "clusterId": cluster_id, "projectId": project, "tenantId": self.org_id,
                               "createdAt": created_at, "expiration": "2026-11-27T02:00:00Z", "retention": retention,
                               "type": type_, "progress": {"status": status, "time": created_at},
                               "crossRegionCopies": [], "cmek": [], "server": {"version": "8.0.1"},
                               "databaseSize": 42 * 1024 ** 3, "_done_at": -1.0, **fields}
        return str(sid)

    def seed_bucket_backup(self, cluster_id: str, bucket: str, method: str = "full", source: str = "scheduled",
                           cycle: str | None = None, date: str = "2026-10-27T02:00:00Z", status: str = "ready",
                           **fields: Any) -> str:
        """A backup of a bucket, in `cycle` (a new cycle when not given)."""
        i = fields.pop("id", None) or self._new_id("bk")
        cyc = cycle or self._new_id("cycle")
        self.backups[i] = {"id": i, "clusterID": cluster_id, "tenantID": self.org_id,
                           "projectID": self.clusters[cluster_id]["project"], "cycleID": cyc, "date": date,
                           "restoreBefore": "2026-11-26T02:00:00Z", "status": status, "method": method,
                           "bucketName": bucket, "bucketID": bucket_id(bucket), "source": source, "provider": "aws",
                           "stats": {"sizeInMb": 3100.0, "items": 912000, "mutations": 912000, "tombstones": 0,
                                     "gsi": 2, "fts": 0, "cbas": 0, "event": 0},
                           "elapsedTimeInSeconds": 120,
                           "scheduleInfo": {"backupType": "weekly", "backupTime": date, "increment": 24,
                                            "retention": "30days"},
                           "_done_at": -1.0, **fields}
        return str(i)

    def _snapshot_view(self, s: dict[str, Any]) -> dict[str, Any]:
        view = {k: copy.deepcopy(v) for k, v in s.items() if not k.startswith("_")}
        if s["_done_at"] >= 0 and self.clock.monotonic() >= s["_done_at"] and view["progress"]["status"] == "pending":
            view["progress"]["status"] = "complete"
            s["progress"]["status"] = "complete"
        return view

    def _backup_view(self, b: dict[str, Any]) -> dict[str, Any]:
        if b["_done_at"] >= 0 and self.clock.monotonic() >= b["_done_at"] and b["status"] == "pending":
            b["status"] = b.pop("_final", "ready")
        return {k: copy.deepcopy(v) for k, v in b.items() if not k.startswith("_")}

    # ------------------------------------------------------------ state
    def set_transition(self, cluster_id: str, path: list[str], step_seconds: float | None = None) -> None:
        step = self.step_seconds if step_seconds is None else step_seconds
        now = self.clock.monotonic()
        self.clusters[cluster_id]["seq"] = [(s, now + i * step) for i, s in enumerate(path)]

    def cluster_state(self, cluster_id: str) -> str:
        now = self.clock.monotonic()
        state = self.clusters[cluster_id]["seq"][0][0]
        for s, at in self.clusters[cluster_id]["seq"]:
            if at <= now:
                state = s
        return str(state)

    def fail_destroy(self, cluster_id: str) -> None:
        """The next DELETE of this cluster is accepted, then the cluster ends in destroyFailed."""
        self.clusters[cluster_id]["destroy_fails"] = True

    def advance(self, seconds: float) -> None:
        self.clock.advance(seconds)

    # ------------------------------------------------------------ faults & calls
    def fail_next(self, method: str, path_glob: str, status: int | None = None, code: int | None = None,
                  times: int = 1, headers: dict[str, str] | None = None, exc: BaseException | None = None,
                  before: Callable[[], None] | None = None) -> None:
        """Make the next `times` matching calls fail. `before` runs first (e.g. to simulate a race)."""
        self._faults.append(_Fault(method.upper(), path_glob, status, code, times, headers or {}, exc, before))

    def calls(self, method: str | None = None, path_glob: str | None = None) -> list[Call]:
        return [c for c in self._calls if (method is None or c.method == method.upper())
                and (path_glob is None or fnmatch.fnmatch(c.path, path_glob))]

    def writes(self) -> list[Call]:
        return [c for c in self._calls if c.method in ("POST", "PUT", "DELETE", "PATCH")]

    def reset_calls(self) -> None:
        self._calls.clear()

    # ------------------------------------------------------------ dispatch
    def _dispatch(self, request: Any) -> Resp:
        parts = urlsplit(request.url)
        path = parts.path
        query = parse_qs(parts.query)
        raw = request.body
        if isinstance(raw, bytes):
            raw = raw.decode()
        body = json.loads(raw) if raw else None
        headers = dict(request.headers)
        method = request.method.upper()
        self._calls.append(Call(method, path, body, headers, query))
        for hook in list(self.hooks):
            hook(method, path)

        for f in list(self._faults):
            if f.method == method and fnmatch.fnmatch(path, f.glob) and f.times > 0:
                f.times -= 1
                if f.times == 0:
                    self._faults.remove(f)
                if f.before is not None:
                    f.before()
                if f.exc is not None:
                    raise f.exc
                assert f.status is not None
                status, h, text = _err(f.status, f"injected {f.status}", f.code)
                h.update(f.headers)
                return status, h, text

        auth = headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or (self.api_keys is not None and auth[7:] not in self.api_keys):
            return _err(401, "Unauthorized", 1001,
                        "The request is unauthorized. Please ensure you have provided appropriate credentials in the "
                        "request header. Please make sure the client IP that is trying to access the resource using "
                        "the API key is in the API key allowlist.")

        for m, rx, handler in self._routes:
            if m != method:
                continue
            match = rx.match(path)
            if match:
                return handler(*match.groups(), body=body, headers=headers, query=query)
        raise AssertionError(f"FakeCapella: unhandled {method} {path}")

    def _route(self, method: str, template: str, handler: Callable[..., Resp]) -> None:
        rx = "^" + re.sub(r"\{[^}]+\}", "([^/]+)", template) + "$"
        self._routes.append((method, re.compile(rx), handler))

    # ------------------------------------------------------------ helpers
    def _page(self, items: list[Any], query: dict[str, list[str]]) -> Resp:
        per = int((query.get("perPage") or ["10"])[0])
        page = int((query.get("page") or ["1"])[0])
        last = max(1, -(-len(items) // per))
        chunk = items[(page - 1) * per: page * per]
        pages: dict[str, Any] = {"page": page, "last": last, "perPage": per, "totalItems": len(items)}
        if page < last:
            pages["next"] = page + 1
        if page > 1:
            pages["previous"] = page - 1
        href = f"{self.base_url}{{}}?page={{}}&perPage={per}"  # Capella's hrefs; the path is not needed here
        hrefs = {"first": href.format("", 1), "last": href.format("", last),
                 "previous": href.format("", page - 1) if page > 1 else "",
                 "next": href.format("", page + 1) if page < last else ""}
        return _ok(200, {"data": chunk, "cursor": {"pages": pages, "hrefs": hrefs}})

    @staticmethod
    def _list(items: list[Any]) -> Resp:
        """A list Capella does not paginate (organizations, buckets, collections): no cursor."""
        return _ok(200, {"data": items})

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]:
        """A stored resource as Capella returns it: without the fake's own `_` fields, with an audit block."""
        return {"audit": audit(), **{k: v for k, v in item.items() if not k.startswith("_")}}

    def _etag_check(self, key: str, headers: dict[str, str]) -> Resp | None:
        want = headers.get("If-Match")
        if want is not None and want.strip('"') != str(self.versions.get(key, 1)):  # GET reports 1 when unset
            return _err(412, "The resource has been modified (ETag mismatch).", 4120)
        return None

    def _org(self, org: str) -> Resp | None:
        if org not in self.orgs:
            return _err(404, f"organization {org} not found", 4040)
        return None

    def _cluster(self, org: str, pid: str, cid: str) -> tuple[dict[str, Any] | None, Resp | None]:
        if (r := self._org(org)) is not None:
            return None, r
        c = self.clusters.get(cid)
        if c is None or c["project"] != pid:
            return None, _err(404, f"cluster {cid} not found", 4041)
        if c["deleted_at"] is not None and self.clock.monotonic() >= c["deleted_at"]:
            del self.clusters[cid]
            return None, _err(404, f"cluster {cid} not found", 4041)
        return c, None

    def _cluster_stats(self, cid: str) -> dict[str, Any]:
        """GET …/stats and the free-tier bucket list's clusterStats: memory left after bucket quotas, n-1 replicas."""
        used = sum(b["memoryAllocationInMb"] for (c, _), b in self.buckets.items() if c == cid)
        groups = self.clusters[cid]["body"].get("serviceGroups") or []
        data_nodes = sum(g["numOfNodes"] for g in groups if "data" in g["services"])
        return {"totalMemoryInMb": self.cluster_total_memory_mb, "freeMemoryInMb": self.cluster_total_memory_mb - used,
                "maxReplicas": max(0, data_nodes - 1)}

    def _cluster_view(self, cid: str) -> dict[str, Any]:
        c = self.clusters[cid]
        body = copy.deepcopy(c["body"])
        body["currentState"] = "destroying" if c["deleted_at"] is not None else self.cluster_state(cid)
        return body

    # ------------------------------------------------------------ routes
    def _build_routes(self) -> None:  # noqa: C901 - a flat routing table is the clearest form here
        ORG = "/v4/organizations/{o}"
        PRJ = ORG + "/projects/{p}"
        CLU = PRJ + "/clusters/{c}"
        BKT = CLU + "/buckets/{b}"
        r = self._route

        # Organizations
        r("GET", "/v4/organizations", lambda **k: self._list(list(self.orgs.values())))
        r("GET", ORG, lambda o, **k: self._org(o) or _ok(200, self.orgs[o]))

        # Projects
        def list_projects(o: str, **k: Any) -> Resp:
            return self._org(o) or self._page(list(self.projects.values()), k["query"])

        def create_project(o: str, body: Any, **k: Any) -> Resp:
            if (e := self._org(o)) is not None:
                return e
            if not (body or {}).get("name"):
                return _err(422, "name is required", 4220)
            pid = self.seed_project(body["name"], description=body.get("description", ""))
            return _ok(201, {"id": pid})

        def get_project(o: str, p: str, **k: Any) -> Resp:
            if p not in self.projects:
                return _err(404, f"project {p} not found", 4042)
            return _ok(200, self.projects[p], {"ETag": f"Version: {self.versions.get(f'project:{p}', 1)}"})

        def put_project(o: str, p: str, body: Any, headers: dict[str, str], **k: Any) -> Resp:
            if p not in self.projects:
                return _err(404, f"project {p} not found", 4042)
            if (e := self._etag_check(f"project:{p}", headers)) is not None:
                return e
            if not (body or {}).get("name"):
                return _err(422, "name is required", 4220)
            self.projects[p].update({"name": body["name"], "description": body.get("description", "")})
            self._bump(f"project:{p}")
            return _ok(204)

        def delete_project(o: str, p: str, **k: Any) -> Resp:
            if p not in self.projects:
                return _err(404, f"project {p} not found", 4042)
            if any(c["project"] == p for c in self.clusters.values()):
                return _err(409, "There is a conflict with the current state of a resource.", 1010,
                            "The project still contains clusters.")
            del self.projects[p]
            return _ok(204)

        r("GET", ORG + "/projects", list_projects)
        r("POST", ORG + "/projects", create_project)
        r("GET", PRJ, get_project)
        r("PUT", PRJ, put_project)
        r("DELETE", PRJ, delete_project)

        # Clusters
        def list_clusters(o: str, p: str, **k: Any) -> Resp:
            if p not in self.projects:
                return _err(404, f"project {p} not found", 4042)
            ids = [cid for cid, c in list(self.clusters.items()) if c["project"] == p
                   and not (c["deleted_at"] is not None and self.clock.monotonic() >= c["deleted_at"])]
            # The list reports deletionProtection for every cluster, free tier included (its own GET does not).
            return self._page([{"deletionProtection": False, **self._cluster_view(cid)} for cid in ids], k["query"])

        def create_cluster(o: str, p: str, body: Any, **k: Any) -> Resp:
            if p not in self.projects:
                return _err(404, f"project {p} not found", 4042)
            body = body or {}
            for f in ("name", "cloudProvider", "serviceGroups", "availability", "support"):
                if f not in body:
                    return _err(422, f"{f} is required", 4221)
            if body["cloudProvider"].get("type") not in ("aws", "gcp", "azure"):
                return _err(422, "invalid cloud provider", 4222)
            if (e := self._azure_disk_check(body["cloudProvider"].get("type"), body["serviceGroups"])) is not None:
                return e
            body = copy.deepcopy(body)
            for g in body["serviceGroups"] if body["cloudProvider"].get("type") == "azure" else []:
                disk = g.get("node", {}).get("disk", {})  # like Capella: a premium disk reports its fixed size
                if disk.get("type") in AZURE_FIXED_DISKS:
                    disk.update(zip(("storage", "iops"), AZURE_FIXED_DISKS[disk["type"]], strict=True))
            fields = {k2: v for k2, v in body.items() if k2 != "name"}
            fields.setdefault("couchbaseServer", {"version": "8.0.1"})
            cid = self.seed_cluster(p, body["name"], **fields)
            self.set_transition(cid, ["deploying", "deploymentFailed" if self.fail_deploy_next else "healthy"])
            self.fail_deploy_next = False
            return _ok(202, {"id": cid})

        def get_cluster(o: str, p: str, c: str, **k: Any) -> Resp:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            return _ok(200, self._cluster_view(c), {"ETag": f"Version: {self.versions.get(f'cluster:{c}', 1)}"})

        def put_cluster(o: str, p: str, c: str, body: Any, headers: dict[str, str], **k: Any) -> Resp:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            if (e := self._etag_check(f"cluster:{c}", headers)) is not None:
                return e
            for f in ("name", "description", "support", "serviceGroups"):
                if f not in (body or {}):
                    return _err(422, f"{f} is required", 4223)
            assert cl is not None
            provider = (cl["body"].get("cloudProvider") or {}).get("type")
            if (e := self._azure_disk_check(provider, body["serviceGroups"])) is not None:
                return e
            groups = copy.deepcopy(body["serviceGroups"])
            for g in groups if provider == "azure" else []:
                disk = g.get("node", {}).get("disk", {})
                if disk.get("type") in AZURE_FIXED_DISKS:
                    disk.update(zip(("storage", "iops"), AZURE_FIXED_DISKS[disk["type"]], strict=True))
            for f in ("name", "description", "support"):
                cl["body"][f] = copy.deepcopy(body[f])
            cl["body"]["serviceGroups"] = groups
            self._bump(f"cluster:{c}")
            self.set_transition(c, ["scaling", "healthy"])
            return _ok(204)

        def delete_cluster(o: str, p: str, c: str, **k: Any) -> Resp:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            assert cl is not None
            if cl["body"].get("deletionProtection"):
                return _err(422, "Deletion protection is enabled for this cluster.", 4224)
            if cl.get("destroy_fails"):
                self.set_transition(c, ["destroying", "destroyFailed"])
                return _ok(202)
            cl["deleted_at"] = self.clock.monotonic() + self.step_seconds
            return _ok(202)

        def protection(o: str, p: str, c: str, body: Any, **k: Any) -> Resp:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            assert cl is not None
            cl["body"]["deletionProtection"] = bool((body or {}).get("deletionProtection"))
            return _ok(204)

        def power_on(o: str, p: str, c: str, **k: Any) -> Resp:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            self.set_transition(c, ["turningOn", "healthy"])
            return _ok(202)

        def power_off(o: str, p: str, c: str, **k: Any) -> Resp:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            self.set_transition(c, ["turningOff", "turnedOff"])
            return _ok(202)

        def stats(o: str, p: str, c: str, **k: Any) -> Resp:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            return _ok(200, self._cluster_stats(c))

        # Free tier (one per organization; listed with the other clusters, support.plan "free")
        def free_create(o: str, p: str, body: Any, **k: Any) -> Resp:
            if p not in self.projects:
                return _err(404, f"project {p} not found", 4042)
            if any(c["body"].get("support", {}).get("plan") == "free" and c["deleted_at"] is None
                   for c in self.clusters.values()):
                return _err(422, "Only one free tier cluster is allowed per tenant.", 4226)
            body = body or {}
            for f in ("name", "cloudProvider"):
                if f not in body:
                    return _err(422, f"{f} is required", 4221)
            cid = self.seed_free_cluster(p, body["name"], description=body.get("description", ""),
                                         cloudProvider=body["cloudProvider"])
            self.set_transition(cid, ["deploying", "healthy"])
            return _ok(202, {"id": cid})

        def free_get(o: str, p: str, c: str, **k: Any) -> Resp:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            assert cl is not None
            if cl["body"].get("support", {}).get("plan") != "free":
                return _err(404, f"free tier cluster {c} not found", 4049)
            return _ok(200, self._cluster_view(c), {"ETag": f"Version: {self.versions.get(f'cluster:{c}', 1)}"})

        def free_put(o: str, p: str, c: str, body: Any, headers: dict[str, str], **k: Any) -> Resp:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            if (e := self._etag_check(f"cluster:{c}", headers)) is not None:
                return e
            assert cl is not None
            for f in ("name", "description"):
                if f not in (body or {}):
                    return _err(422, f"{f} is required", 4223)
                cl["body"][f] = body[f]
            self._bump(f"cluster:{c}")
            return _ok(204)

        def free_delete(o: str, p: str, c: str, **k: Any) -> Resp:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            assert cl is not None
            cl["deleted_at"] = self.clock.monotonic() + self.step_seconds
            return _ok(202)

        r("POST", PRJ + "/clusters/freeTier/{c}/activationState", power_on)
        r("DELETE", PRJ + "/clusters/freeTier/{c}/activationState", power_off)
        r("POST", PRJ + "/clusters/freeTier", free_create)
        r("GET", PRJ + "/clusters/freeTier/{c}", free_get)
        r("PUT", PRJ + "/clusters/freeTier/{c}", free_put)
        r("DELETE", PRJ + "/clusters/freeTier/{c}", free_delete)
        r("GET", PRJ + "/clusters", list_clusters)
        r("POST", PRJ + "/clusters", create_cluster)
        r("GET", CLU, get_cluster)
        r("PUT", CLU, put_cluster)
        r("DELETE", CLU, delete_cluster)
        r("PUT", CLU + "/deletionProtection", protection)
        r("POST", CLU + "/activationState", power_on)
        r("DELETE", CLU + "/activationState", power_off)
        r("GET", CLU + "/stats", stats)

        # On/Off schedule
        def sched_get(o: str, p: str, c: str, **k: Any) -> Resp:
            if (e := self._cluster(o, p, c)[1]) is not None:
                return e
            if c not in self.schedules:
                return _err(404, "no on/off schedule for this cluster", 4043)
            return _ok(200, self.schedules[c], {"ETag": f"Version: {self.versions.get(f'schedule:{c}', 1)}"})

        def sched_post(o: str, p: str, c: str, body: Any, **k: Any) -> Resp:
            if (e := self._cluster(o, p, c)[1]) is not None:
                return e
            if c in self.schedules:
                return _err(409, "There is a conflict with the current state of a resource.", 1010)
            if len((body or {}).get("days") or []) != 7:
                return _err(422, "The On/Off schedule requires 7 days.", 4225)
            self.schedules[c] = {"activationStatus": "active", **body}
            self._bump(f"schedule:{c}")
            return _ok(204)

        def sched_put(o: str, p: str, c: str, body: Any, headers: dict[str, str], **k: Any) -> Resp:
            if c not in self.schedules:
                return _err(404, "no on/off schedule for this cluster", 4043)
            if (e := self._etag_check(f"schedule:{c}", headers)) is not None:
                return e
            self.schedules[c].update(body or {})
            self._bump(f"schedule:{c}")
            return _ok(204)

        def sched_delete(o: str, p: str, c: str, **k: Any) -> Resp:
            if self.schedules.pop(c, None) is None:
                return _err(404, "no on/off schedule for this cluster", 4043)
            return _ok(204)

        def sched_status(status: str) -> Callable[..., Resp]:
            def h(o: str, p: str, c: str, **k: Any) -> Resp:
                if c not in self.schedules:
                    return _err(404, "no on/off schedule for this cluster", 4043)
                self.schedules[c]["activationStatus"] = status
                return _ok(204)
            return h

        r("GET", CLU + "/onOffSchedule", sched_get)
        r("POST", CLU + "/onOffSchedule", sched_post)
        r("PUT", CLU + "/onOffSchedule", sched_put)
        r("DELETE", CLU + "/onOffSchedule", sched_delete)
        r("POST", CLU + "/onOffSchedule/activationState", sched_status("active"))
        r("DELETE", CLU + "/onOffSchedule/activationState", sched_status("paused"))

        # Allowed CIDRs
        def cidr_list(o: str, p: str, c: str, **k: Any) -> Resp:
            if (e := self._cluster(o, p, c)[1]) is not None:
                return e
            return self._page([self._public(v) for v in self.cidrs.values() if v["_cluster"] == c], k["query"])

        def cidr_create(o: str, p: str, c: str, body: Any, **k: Any) -> Resp:
            if (e := self._cluster(o, p, c)[1]) is not None:
                return e
            if not self.cidr_duplicates_allowed and \
                    any(v["_cluster"] == c and v["cidr"] == body.get("cidr") for v in self.cidrs.values()):
                return _err(409, "There is a conflict with the current state of a resource.", 1010)
            i = self._new_id("cidr")
            self.cidrs[i] = {"id": i, "_cluster": c, "status": "active",
                             "type": "temporary" if body.get("expiresAt") else "permanent", **body}
            return _ok(201, {"id": i})

        def cidr_get(o: str, p: str, c: str, i: str, **k: Any) -> Resp:
            return _ok(200, self._public(self.cidrs[i])) if i in self.cidrs else _err(404, "not found", 4044)

        def cidr_delete(o: str, p: str, c: str, i: str, **k: Any) -> Resp:
            return _ok(204) if self.cidrs.pop(i, None) else _err(404, "not found", 4044)

        r("GET", CLU + "/allowedcidrs", cidr_list)
        r("POST", CLU + "/allowedcidrs", cidr_create)
        r("GET", CLU + "/allowedcidrs/{i}", cidr_get)
        r("DELETE", CLU + "/allowedcidrs/{i}", cidr_delete)

        # Buckets
        def b_list(o: str, p: str, c: str, **k: Any) -> Resp:
            if (e := self._cluster(o, p, c)[1]) is not None:
                return e
            return self._list([v for (cid, _), v in self.buckets.items() if cid == c])

        def b_create(o: str, p: str, c: str, body: Any, **k: Any) -> Resp:
            if (e := self._cluster(o, p, c)[1]) is not None:
                return e
            bid = bucket_id(body["name"])
            if (c, bid) in self.buckets:
                return _err(409, "There is a conflict with the current state of a resource.", 1010)
            fields = {k2: v for k2, v in body.items() if k2 != "name"}
            self.seed_bucket(c, body["name"], **fields)
            return _ok(201, {"id": bid})

        def b_get(o: str, p: str, c: str, b: str, **k: Any) -> Resp:
            return _ok(200, self.buckets[(c, b)]) if (c, b) in self.buckets else _err(404, "bucket not found", 4045)

        def b_put(o: str, p: str, c: str, b: str, body: Any, **k: Any) -> Resp:
            if (c, b) not in self.buckets:
                return _err(404, "bucket not found", 4045)
            self.buckets[(c, b)].update(body or {})
            return _ok(204)

        def b_delete(o: str, p: str, c: str, b: str, **k: Any) -> Resp:
            if self.buckets.pop((c, b), None) is None:
                return _err(404, "bucket not found", 4045)
            self.scopes.pop((c, b), None)
            return _ok(204)

        # Free-tier buckets (registered first: BKT would also match /buckets/freeTier)
        def fb_cluster(o: str, p: str, c: str) -> Resp | None:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            if str((cl["body"].get("support") or {}).get("plan")) != "free":  # type: ignore[index]
                return _err(422, "You can only create a free tier bucket on a free tier cluster.", 4220)
            return None

        def fb_list(o: str, p: str, c: str, **k: Any) -> Resp:
            if (e := fb_cluster(o, p, c)) is not None:
                return e
            return _ok(200, {"data": [v for (cid, _), v in self.buckets.items() if cid == c],
                             "clusterStats": self._cluster_stats(c)})

        def fb_create(o: str, p: str, c: str, body: Any, **k: Any) -> Resp:
            if (e := fb_cluster(o, p, c)) is not None:
                return e
            extra = set(body) - {"name", "memoryAllocationInMb"}
            if extra:
                return _err(422, f"unknown fields for a free tier bucket: {sorted(extra)}", 4220)
            if (c, bucket_id(body["name"])) in self.buckets:
                return _err(409, "There is a conflict with the current state of a resource.", 1010)
            bid = self.seed_bucket(c, body["name"], memoryAllocationInMb=body.get("memoryAllocationInMb", 100),
                                   enableCrossClusterVersioning=False)
            return _ok(201, {"id": bid})

        def fb_put(o: str, p: str, c: str, b: str, body: Any, **k: Any) -> Resp:
            if (e := fb_cluster(o, p, c)) is not None:
                return e
            if (c, b) not in self.buckets:
                return _err(404, "bucket not found", 4045)
            if set(body or {}) - {"memoryAllocationInMb", "enableCrossClusterVersioning"} or \
                    "memoryAllocationInMb" not in (body or {}):
                return _err(422, "a free tier bucket update takes memoryAllocationInMb and "
                                 "enableCrossClusterVersioning", 4220)
            self.buckets[(c, b)].update(body)
            return _ok(204)

        def fb_get(o: str, p: str, c: str, b: str, **k: Any) -> Resp:
            if (e := fb_cluster(o, p, c)) is not None:
                return e
            return b_get(o, p, c, b)

        def fb_delete(o: str, p: str, c: str, b: str, **k: Any) -> Resp:
            if (e := fb_cluster(o, p, c)) is not None:
                return e
            return b_delete(o, p, c, b)

        r("GET", CLU + "/buckets/freeTier", fb_list)
        r("POST", CLU + "/buckets/freeTier", fb_create)
        r("GET", CLU + "/buckets/freeTier/{b}", fb_get)
        r("PUT", CLU + "/buckets/freeTier/{b}", fb_put)
        r("DELETE", CLU + "/buckets/freeTier/{b}", fb_delete)
        r("GET", CLU + "/buckets", b_list)
        r("POST", CLU + "/buckets", b_create)
        r("GET", BKT, b_get)
        r("PUT", BKT, b_put)
        r("DELETE", BKT, b_delete)

        # Scopes & collections
        def s_list(o: str, p: str, c: str, b: str, **k: Any) -> Resp:
            sc = self.scopes.get((c, b))
            if sc is None:
                return _err(404, "bucket not found", 4045)
            return _ok(200, {"scopes": [{"name": n, "collections": list(cols.values())} for n, cols in sc.items()]})

        def s_create(o: str, p: str, c: str, b: str, body: Any, **k: Any) -> Resp:
            sc = self.scopes.get((c, b))
            if sc is None:
                return _err(404, "bucket not found", 4045)
            if body["name"] in sc:
                return _err(409, "There is a conflict with the current state of a resource.", 1010)
            sc[body["name"]] = {}
            return _ok(201)

        def s_get(o: str, p: str, c: str, b: str, s: str, **k: Any) -> Resp:
            sc = self.scopes.get((c, b)) or {}
            if s not in sc:
                return _err(404, "scope not found", 4046)
            return _ok(200, {"name": s, "collections": list(sc[s].values())})

        def s_delete(o: str, p: str, c: str, b: str, s: str, **k: Any) -> Resp:
            sc = self.scopes.get((c, b)) or {}
            return _ok(204) if sc.pop(s, None) is not None else _err(404, "scope not found", 4046)

        def col_list(o: str, p: str, c: str, b: str, s: str, **k: Any) -> Resp:
            sc = self.scopes.get((c, b)) or {}
            if s not in sc:
                return _err(404, "scope not found", 4046)
            return self._list(list(sc[s].values()))

        def col_create(o: str, p: str, c: str, b: str, s: str, body: Any, **k: Any) -> Resp:
            sc = self.scopes.get((c, b)) or {}
            if s not in sc:
                return _err(404, "scope not found", 4046)
            if body["name"] in sc[s]:
                return _err(409, "There is a conflict with the current state of a resource.", 1010)
            sc[s][body["name"]] = {"name": body["name"], "maxTTL": body.get("maxTTL", 0)}
            self._bump(f"collection:{c}/{b}/{s}/{body['name']}")
            return _ok(201)

        def col_get(o: str, p: str, c: str, b: str, s: str, n: str, **k: Any) -> Resp:
            col = ((self.scopes.get((c, b)) or {}).get(s) or {}).get(n)
            if col is None:
                return _err(404, "collection not found", 4047)
            return _ok(200, col, {"ETag": f"Version: {self.versions.get(f'collection:{c}/{b}/{s}/{n}', 1)}"})

        def col_put(o: str, p: str, c: str, b: str, s: str, n: str, body: Any, headers: dict[str, str], **k: Any) -> Resp:
            col = ((self.scopes.get((c, b)) or {}).get(s) or {}).get(n)
            if col is None:
                return _err(404, "collection not found", 4047)
            if (e := self._etag_check(f"collection:{c}/{b}/{s}/{n}", headers)) is not None:
                return e
            col["maxTTL"] = body["maxTTL"]
            self._bump(f"collection:{c}/{b}/{s}/{n}")
            return _ok(204)

        def col_delete(o: str, p: str, c: str, b: str, s: str, n: str, **k: Any) -> Resp:
            sc = (self.scopes.get((c, b)) or {}).get(s) or {}
            return _ok(204) if sc.pop(n, None) is not None else _err(404, "collection not found", 4047)

        r("GET", BKT + "/scopes", s_list)
        r("POST", BKT + "/scopes", s_create)
        r("GET", BKT + "/scopes/{s}", s_get)
        r("DELETE", BKT + "/scopes/{s}", s_delete)
        r("GET", BKT + "/scopes/{s}/collections", col_list)
        r("POST", BKT + "/scopes/{s}/collections", col_create)
        r("GET", BKT + "/scopes/{s}/collections/{n}", col_get)
        r("PUT", BKT + "/scopes/{s}/collections/{n}", col_put)
        r("DELETE", BKT + "/scopes/{s}/collections/{n}", col_delete)

        # Database credentials
        def u_list(o: str, p: str, c: str, **k: Any) -> Resp:
            if (e := self._cluster(o, p, c)[1]) is not None:
                return e
            return self._page([self._user_view(u) for u in self.users.values() if u["_cluster"] == c], k["query"])

        def u_create(o: str, p: str, c: str, body: Any, **k: Any) -> Resp:
            if (e := self._cluster(o, p, c)[1]) is not None:
                return e
            if any(u["_cluster"] == c and u["name"] == body["name"] for u in self.users.values()):
                return _err(409, "There is a conflict with the current state of a resource.", 1010)
            i = self._new_id("u")
            password = body.get("password") or f"Gen3rated!Pw-{i}"
            self.users[i] = {"id": i, "_cluster": c, "name": body["name"], "access": body.get("access", []),
                             "userRoles": body.get("userRoles"), "_password": password}
            self._bump(f"user:{i}")
            return _ok(201, {"id": i, "password": password})

        def u_get(o: str, p: str, c: str, i: str, **k: Any) -> Resp:
            if i not in self.users:
                return _err(404, "credential not found", 4048)
            return _ok(200, self._user_view(self.users[i]), {"ETag": f"Version: {self.versions.get(f'user:{i}', 1)}"})

        def u_put(o: str, p: str, c: str, i: str, body: Any, headers: dict[str, str], **k: Any) -> Resp:
            if i not in self.users:
                return _err(404, "credential not found", 4048)
            if (e := self._etag_check(f"user:{i}", headers)) is not None:
                return e
            if "access" in (body or {}):
                self.users[i]["access"] = body["access"]
            elif not self.users[i].get("userRoles"):  # like Capella: a basic credential PUT without access clears it
                self.users[i]["access"] = []
            if (body or {}).get("password"):
                self.users[i]["_password"] = body["password"]
            self._bump(f"user:{i}")
            return _ok(204)

        def u_delete(o: str, p: str, c: str, i: str, **k: Any) -> Resp:
            return _ok(204) if self.users.pop(i, None) else _err(404, "credential not found", 4048)

        self._build_backup_routes(CLU, BKT, PRJ)
        r("GET", CLU + "/users", u_list)
        r("POST", CLU + "/users", u_create)
        r("GET", CLU + "/users/{i}", u_get)
        r("PUT", CLU + "/users/{i}", u_put)
        r("DELETE", CLU + "/users/{i}", u_delete)

    def _build_backup_routes(self, CLU: str, BKT: str, PRJ: str) -> None:  # noqa: C901, N803 - one table
        r = self._route

        def snapshot_cluster(o: str, p: str, c: str) -> Resp | None:
            cl, e = self._cluster(o, p, c)
            if e is not None:
                return e
            if str((cl["body"].get("support") or {}).get("plan")) == "free":  # type: ignore[index]
                return _err(422, "Backups are not available for free tier clusters.", 4220)
            return None

        # Cloud snapshot backup schedule (GET: 204 when there is none)
        def ss_get(o: str, p: str, c: str, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            body = self.snapshot_schedules.get(c)
            return _ok(200, body) if body is not None else _ok(204)

        def ss_put(o: str, p: str, c: str, body: Any, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            body = body or {}
            opts = self.snapshot_options
            if body.get("interval") not in opts["intervals"]:
                return _err(422, f"interval must be one of {opts['intervals']}", 4220)
            if not opts["minimumRetention"] <= int(body.get("retention") or 0) <= opts["maximumRetention"]:
                return _err(422, "retention is outside the range the service plan permits", 4220)
            if any(x not in self.snapshot_regions for x in body.get("copyToRegions") or []):
                return _err(422, "copyToRegions has a region that is not available", 4220)
            self.snapshot_schedules[c] = {k2: copy.deepcopy(v) for k2, v in body.items()
                                          if k2 in ("interval", "retention", "startTime", "copyToRegions")}
            return _ok(204)

        def ss_delete(o: str, p: str, c: str, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            self.snapshot_schedules.pop(c, None)
            return _ok(204)

        def ss_options(o: str, p: str, c: str, **k: Any) -> Resp:
            return snapshot_cluster(o, p, c) or _ok(200, copy.deepcopy(self.snapshot_options))

        r("GET", CLU + "/cloudsnapshotbackupschedule/options", ss_options)
        r("GET", CLU + "/cloudsnapshotbackupschedule", ss_get)
        r("PUT", CLU + "/cloudsnapshotbackupschedule", ss_put)
        r("DELETE", CLU + "/cloudsnapshotbackupschedule", ss_delete)

        # Cloud snapshot backups (registered before …/cloudsnapshotbackups/{backupId})
        def cs_regions(o: str, p: str, c: str, **k: Any) -> Resp:
            return snapshot_cluster(o, p, c) or _ok(200, list(self.snapshot_regions))

        def cs_list(o: str, p: str, c: str, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            items = [self._snapshot_view(s) for s in self.snapshots.values() if s["clusterId"] == c]
            return self._page(sorted(items, key=lambda s: s["createdAt"], reverse=True), k["query"])

        def cs_project(o: str, p: str, **k: Any) -> Resp:
            if p not in self.projects:
                return _err(404, f"project {p} not found", 4042)
            rows = []
            for cid, cl in self.clusters.items():
                snaps = sorted((self._snapshot_view(s) for s in self.snapshots.values() if s["clusterId"] == cid),
                               key=lambda s: s["createdAt"])
                if cl["project"] != p or not snaps:
                    continue
                cp = cl["body"].get("cloudProvider") or {}
                rows.append({"clusterId": cid, "clusterName": cl["body"]["name"], "currentStatus": self.cluster_state(cid),
                             "cloudProvider": f"hosted{str(cp.get('type', 'aws')).upper()}", "region": cp.get("region"),
                             "creationDateTime": "2026-01-01T00:00:00Z", "createdBy": "fake-api-key",
                             "mostRecentSnapshot": snaps[-1], "oldestSnapshot": snaps[0]})
            return self._page(rows, k["query"])

        def cs_create(o: str, p: str, c: str, body: Any, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            body = body or {}
            regions = body.get("regionsToCopy") or []
            if len(regions) > 2 or any(x not in self.snapshot_regions for x in regions):
                return _err(422, "regionsToCopy: at most two of the available regions", 4220)
            sid = self.seed_snapshot(c, created_at=f"2026-10-29T{len(self.snapshots) % 24:02d}:00:00Z",
                                     retention=int(body.get("retention") or 720), type_="onDemand", status="pending",
                                     crossRegionCopies=[{"regionCode": x, "status": "pending"} for x in regions])
            self.snapshots[sid]["_done_at"] = self.clock.monotonic() + self.step_seconds
            return _ok(202, {"backupId": sid})

        def cs_restores(o: str, p: str, c: str, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            items = []
            for rs in self.snapshot_restores.values():
                if rs["clusterId"] != c:
                    continue
                view = {k2: v for k2, v in rs.items() if not k2.startswith("_")}
                if self.clock.monotonic() >= rs["_done_at"]:
                    view.update(status="complete", restoreEnd="2026-10-29T03:00:00Z")
                items.append(view)
            return self._page(items, k["query"])

        def cs_snapshot(c: str, b: str) -> dict[str, Any] | None:
            s = self.snapshots.get(b)
            return s if s is not None and s["clusterId"] == c else None

        def cs_put(o: str, p: str, c: str, b: str, body: Any, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            s = cs_snapshot(c, b)
            if s is None:
                return _err(404, "backup not found", 4040)
            s["retention"] = int((body or {}).get("retention") or s["retention"])
            return _ok(204)

        def cs_delete(o: str, p: str, c: str, b: str, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            if cs_snapshot(c, b) is None:
                return _err(404, "backup not found", 4040)
            del self.snapshots[b]
            return _ok(202, {})

        def cs_restore(o: str, p: str, c: str, b: str, body: Any, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            s = cs_snapshot(c, b)
            if s is None:
                return _err(404, "backup not found", 4040)
            if self.cluster_state(c) in ("turnedOff", "turningOff"):
                return _err(422, "The cluster is turned off.", 4220)
            rid = self._new_id("restore")
            self.snapshot_restores[rid] = {"id": rid, "clusterId": c, "projectId": p, "tenantId": self.org_id,
                                           "createdAt": "2026-10-29T02:30:00Z", "restoreTo": c,
                                           "snapshot": s["createdAt"], "status": "pending",
                                           "_done_at": self.clock.monotonic() + self.step_seconds,
                                           "_body": copy.deepcopy(body)}
            self.set_transition(c, ["rebalancing", "healthy"])
            return _ok(202, {"restoreId": rid})

        r("GET", CLU + "/cloudsnapshotbackups/regions", cs_regions)
        r("GET", CLU + "/cloudsnapshotbackups/restores", cs_restores)
        r("GET", CLU + "/cloudsnapshotbackups", cs_list)
        r("POST", CLU + "/cloudsnapshotbackups", cs_create)
        r("PUT", CLU + "/cloudsnapshotbackups/{b}", cs_put)
        r("DELETE", CLU + "/cloudsnapshotbackups/{b}", cs_delete)
        r("POST", CLU + "/cloudsnapshotbackups/{b}/restore", cs_restore)
        r("GET", PRJ + "/cloudsnapshotbackups", cs_project)

        # Bucket backup schedules (GET and PUT: 404 when there is none; POST: 409 when there is one)
        def bucket_ok(o: str, p: str, c: str, b: str) -> Resp | None:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            return None if (c, b) in self.buckets else _err(404, "bucket not found", 4045)

        def schedule_problem(body: Any) -> Resp | None:
            w = (body or {}).get("weeklySchedule") or {}
            rules = {"dayOfWeek": ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"),
                     "startAt": tuple(range(24)), "incrementalEvery": (1, 2, 4, 6, 8, 12, 24),
                     "retentionTime": ("30days", "60days", "90days", "180days", "1year", "2years", "3years", "4years",
                                       "5years"), "costOptimizedRetention": (True, False)}
            if (body or {}).get("type") != "weekly":
                return _err(422, "type must be weekly", 4220)
            for f, allowed in rules.items():
                if w.get(f) not in allowed:
                    return _err(422, f"weeklySchedule.{f} is invalid", 4220)
            return None

        def bs_get(o: str, p: str, c: str, b: str, **k: Any) -> Resp:
            if (e := bucket_ok(o, p, c, b)) is not None:
                return e
            body = self.bucket_backup_schedules.get((c, b))
            if body is None:
                return _err(404, "no backup schedule for this bucket", 4040)
            return _ok(200, {"type": "weekly", "clusterID": c, "bucketId": b, **copy.deepcopy(body)})

        def bs_post(o: str, p: str, c: str, b: str, body: Any, **k: Any) -> Resp:
            if (e := bucket_ok(o, p, c, b) or schedule_problem(body)) is not None:
                return e
            if (c, b) in self.bucket_backup_schedules:
                return _err(409, "There is a conflict with the current state of a resource.", 1010)
            self.bucket_backup_schedules[(c, b)] = {"weeklySchedule": copy.deepcopy(body["weeklySchedule"])}
            return _ok(202)

        def bs_put(o: str, p: str, c: str, b: str, body: Any, **k: Any) -> Resp:
            if (e := bucket_ok(o, p, c, b) or schedule_problem(body)) is not None:
                return e
            if (c, b) not in self.bucket_backup_schedules:
                return _err(404, "no backup schedule for this bucket", 4040)
            self.bucket_backup_schedules[(c, b)] = {"weeklySchedule": copy.deepcopy(body["weeklySchedule"])}
            return _ok(204)

        def bs_delete(o: str, p: str, c: str, b: str, **k: Any) -> Resp:
            if (e := bucket_ok(o, p, c, b)) is not None:
                return e
            if self.bucket_backup_schedules.pop((c, b), None) is None:
                return _err(404, "no backup schedule for this bucket", 4040)
            return _ok(202)

        def cycles(o: str, p: str, c: str, b: str, **k: Any) -> Resp:
            if (e := bucket_ok(o, p, c, b)) is not None:
                return e
            first: dict[str, str] = {}
            for bk in sorted(self.backups.values(), key=lambda x: x["date"]):
                if bk["clusterID"] == c and bk["bucketID"] == b:
                    first.setdefault(bk["cycleID"], bk["date"])
            return _ok(200, {"data": [{"cycleID": cy, "createdAt": at} for cy, at in first.items()]})

        def cycle_get(o: str, p: str, c: str, b: str, y: str, **k: Any) -> Resp:
            if (e := bucket_ok(o, p, c, b)) is not None:
                return e
            items = [self._backup_view(bk) for bk in self.backups.values()
                     if bk["clusterID"] == c and bk["bucketID"] == b and bk["cycleID"] == y]
            if not items:
                return _err(404, "cycle not found", 4040)
            return _ok(200, {"data": [{k2: v for k2, v in i.items() if k2 != "bucketDownloadsCount"} for i in items]})

        r("GET", BKT + "/backup/schedules", bs_get)
        r("POST", BKT + "/backup/schedules", bs_post)
        r("PUT", BKT + "/backup/schedules", bs_put)
        r("DELETE", BKT + "/backup/schedules", bs_delete)
        r("GET", BKT + "/backup/cycles", cycles)
        r("GET", BKT + "/backup/cycles/{y}", cycle_get)

        # Bucket backups
        def bk_create(o: str, p: str, c: str, b: str, **k: Any) -> Resp:
            if (e := bucket_ok(o, p, c, b)) is not None:
                return e
            name = self.buckets[(c, b)]["name"]
            i = self.seed_bucket_backup(c, name, method="full", source="manual", status="pending",
                                        date=f"2026-10-29T{len(self.backups) % 24:02d}:00:00Z")
            self.backups[i]["_done_at"] = self.clock.monotonic() + self.step_seconds
            if self.backup_fails_next:
                self.backups[i]["_final"] = "failed"
                self.backup_fails_next = False
            return _ok(202)

        def bk_list(o: str, p: str, c: str, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            latest: dict[str, dict[str, Any]] = {}
            for bk in sorted(self.backups.values(), key=lambda x: x["date"]):
                if bk["clusterID"] == c:
                    latest[bk["bucketID"]] = bk  # Capella lists the latest backup of each bucket
            return _ok(200, {"data": [{**self._backup_view(bk), "bucketDownloadsCount": 0} for bk in latest.values()]})

        def bk_get(o: str, p: str, c: str, i: str, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            bk = self.backups.get(i)
            if bk is None or bk["clusterID"] != c:
                return _err(404, "backup not found", 4040)
            return _ok(200, self._backup_view(bk))

        def bk_delete(o: str, p: str, c: str, i: str, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            bk = self.backups.get(i)
            if bk is None or bk["clusterID"] != c:
                return _err(404, "backup not found", 4040)
            for j in [j for j, x in self.backups.items() if x["cycleID"] == bk["cycleID"]]:
                del self.backups[j]  # the whole cycle goes
            return _ok(202)

        def bk_restore(o: str, p: str, c: str, i: str, body: Any, **k: Any) -> Resp:
            if (e := snapshot_cluster(o, p, c)) is not None:
                return e
            body = body or {}
            for f in ("targetClusterID", "sourceClusterID", "backupID", "services"):
                if f not in body:
                    return _err(422, f"{f} is required", 4220)
            if i not in self.backups:
                return _err(404, "backup not found", 4040)
            target = self.clusters.get(str(body["targetClusterID"]))
            if target is None:
                return _err(404, "target cluster not found", 4041)
            if self.cluster_state(str(body["targetClusterID"])) in ("turnedOff", "turningOff"):
                return _err(422, "The target cluster is turned off.", 4220)
            self.bucket_restores.append(copy.deepcopy(body))
            return _ok(202)

        def ex_create(o: str, p: str, c: str, b: str, i: str, **k: Any) -> Resp:
            if (e := bucket_ok(o, p, c, b)) is not None:
                return e
            bk = self.backups.get(i)
            if bk is None:
                return _err(404, "backup not found", 4040)
            if self._backup_view(bk)["status"] != "ready":
                return _err(422, "The backup must be in a ready state.", 4220)
            if any(x["cycleId"] == bk["cycleID"] and x["status"] != "failed" for x in self.exports.values()):
                return _err(409, "The backup cycle already has an export.", 1010)
            x = self._new_id("export")
            self.exports[x] = {"id": x, "tenantId": self.org_id, "projectId": p, "clusterId": c,
                               "cycleId": bk["cycleID"], "bucketName": bk["bucketName"], "status": "pending",
                               "createdAt": "2026-10-29T04:00:00Z", "_backup": i,
                               "_done_at": self.clock.monotonic() + self.step_seconds}
            return _ok(202, {"exportId": x, "createdAt": "2026-10-29T04:00:00Z"})

        def ex_get(o: str, p: str, c: str, b: str, i: str, x: str, **k: Any) -> Resp:
            if (e := bucket_ok(o, p, c, b)) is not None:
                return e
            ex = self.exports.get(x)
            if ex is None or ex["_backup"] != i:
                return _err(404, "export not found", 4040)
            view = {k2: v for k2, v in ex.items() if not k2.startswith("_")}
            if self.clock.monotonic() >= ex["_done_at"]:
                view.update(status="complete", sizeInBytes=3 * 1024 ** 3, sha256Checksum="ab" * 32,
                            expiration="2026-10-29T16:00:00Z",
                            backupDownloadURL=f"https://downloads.example.com/{x}.zip?X-Amz-Signature=s3cr3t")
            return _ok(200, view)

        r("POST", BKT + "/backups", bk_create)
        r("POST", BKT + "/backups/{i}/export", ex_create)
        r("GET", BKT + "/backups/{i}/exports/{x}", ex_get)
        r("GET", CLU + "/backups", bk_list)
        r("GET", CLU + "/backups/{i}", bk_get)
        r("DELETE", CLU + "/backups/{i}", bk_delete)
        r("POST", CLU + "/backups/{i}/restore", bk_restore)

    @staticmethod
    def _azure_disk_check(provider: Any, groups: Any) -> Resp | None:
        """Capella: only Ultra disks take a size or IOPS on Azure."""
        for g in groups or [] if provider == "azure" else []:
            disk = (g.get("node") or {}).get("disk") or {}
            if disk.get("type") != "Ultra" and ("storage" in disk or "iops" in disk):
                return _err(422, "Unable to process deployment for cluster. Cannot specify disk size or IOPS for "
                                 f"disk type {disk.get('type')}", 4000)
        return None

    @staticmethod
    def _user_view(u: dict[str, Any]) -> dict[str, Any]:
        view = {"audit": audit(), **{k: v for k, v in u.items() if not k.startswith("_")}}
        if view.get("userRoles") is None:  # basic credentials: Capella leaves userRoles out
            view.pop("userRoles", None)
        # Like Capella: a whole-bucket grant comes back with a wildcard scope, `scopes: [{name: "*"}]`.
        view["access"] = [{**a, "resources": {**a["resources"], "buckets": [
            b if b.get("scopes") else {**b, "scopes": [{"name": "*"}]} for b in a["resources"]["buckets"]]}}
            if (a.get("resources") or {}).get("buckets") else a for a in view.get("access") or []]
        return view
