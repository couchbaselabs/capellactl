"""CAP-004 AC6: the fake's responses match the published Management API v4.0 spec, offline.

Every endpoint capellactl calls is exercised on the fake, and each answer is compared with the operation's documented
success responses in docs/api/management-api-v4.0-responses.json (refresh it with scripts/update-api-responses.py):
the status code must be documented, required fields present, every field documented, and every value of the
documented type. No Capella organization is called.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from capellactl.api.endpoints import INVENTORY
from tests.fakes.capella import bucket_id

SNAPSHOT = Path(__file__).resolve().parents[3] / "docs" / "api" / "management-api-v4.0-responses.json"
SPEC = {(o["method"], o["path"]): o for o in json.loads(SNAPSHOT.read_text(encoding="utf-8"))["operations"]}
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}

GROUPS = [{"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
           "numOfNodes": 3, "services": ["data", "index", "query"]}]
CLUSTER = {"name": "made", "cloudProvider": {"type": "aws", "region": "us-east-1", "cidr": "10.99.0.0/24"},
           "serviceGroups": GROUPS, "availability": {"type": "multi"}, "support": {"plan": "basic"}}
SCHEDULE = {"timezone": "US/Pacific", "days": [{"day": d, "state": "on"} for d in
                                              ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
                                               "sunday")]}
ACCESS = [{"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders"}]}}]
BUCKET_SCHEDULE = {"type": "weekly", "weeklySchedule": {"dayOfWeek": "sunday", "startAt": 2, "incrementalEvery": 24,
                                                        "retentionTime": "30days", "costOptimizedRetention": False}}


def problems(value: Any, schema: dict[str, Any] | None, where: str) -> list[str]:
    """Differences between a response value and its documented schema."""
    if not schema:
        return []
    for key in ("oneOf", "anyOf"):
        if key in schema:
            options = [problems(value, s, where) for s in schema[key]]
            return [] if any(not o for o in options) else min(options, key=len)
    if "allOf" in schema:
        merged: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for s in schema["allOf"]:
            merged["properties"].update(s.get("properties") or {})
            merged["required"] += s.get("required") or []
        schema = {**{k: v for k, v in schema.items() if k != "allOf"}, **merged}
    if value is None:
        return [] if schema.get("nullable") else [f"{where}: null, but the spec does not allow null"]
    t = schema.get("type") or ("object" if "properties" in schema else None)
    if t in TYPES and (not isinstance(value, TYPES[t]) or (t in ("integer", "number") and isinstance(value, bool))):
        return [f"{where}: {type(value).__name__}, the spec says {t}"]
    found: list[str] = []
    if t == "object" and isinstance(value, dict):
        props = schema.get("properties") or {}
        for req in schema.get("required") or []:
            if req not in value:
                found.append(f"{where}.{req}: required by the spec, missing in the fake")
        extra = schema.get("additionalProperties")
        for k, v in value.items():
            if k in props:
                found += problems(v, props[k], f"{where}.{k}")
            elif isinstance(extra, dict):
                found += problems(v, extra, f"{where}.{k}")
            elif props and extra is not True:
                found.append(f"{where}.{k}: returned by the fake, not in the spec")
    if t == "array" and isinstance(value, list):
        for i, item in enumerate(value[:3]):
            found += problems(item, schema.get("items"), f"{where}[{i}]")
    return found


@pytest.fixture
def world(fake):
    pid = fake.seed_project("nova-dev", description="Nova")
    cid = fake.seed_cluster(pid, "nova-dev-01", serviceGroups=GROUPS)
    fid = fake.seed_free_cluster(pid, "try-01")
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=512)
    fake.seed_scope(cid, "orders", "inventory", {"items": 0})
    fake.seed_bucket(fid, "free-b")
    fake.cidrs["cidr-1"] = {"id": "cidr-1", "_cluster": cid, "cidr": "203.0.113.10/32", "status": "active",
                            "comment": "VPN", "type": "permanent", "expiresAt": "",
                            "audit": {"createdBy": "u", "createdAt": "2026-01-01T00:00:00Z", "modifiedBy": "u",
                                      "modifiedAt": "2026-01-01T00:00:00Z", "version": 1}}
    fake.users["u-1"] = {"id": "u-1", "_cluster": cid, "name": "app", "access": ACCESS, "userRoles": None,
                         "_password": "x"}
    fake.versions["user:u-1"] = 1
    fake.schedules[cid] = {"activationStatus": "active", **SCHEDULE}
    fake.snapshot_schedules[cid] = {"interval": 24, "retention": 720, "startTime": "2026-10-30T02:00:00Z",
                                    "copyToRegions": ["us-west-2"]}
    snap = fake.seed_snapshot(cid)
    backup = fake.seed_bucket_backup(cid, "orders", cycle="cycle-1")
    fake.bucket_backup_schedules[(cid, bucket_id("orders"))] = {"weeklySchedule": BUCKET_SCHEDULE["weeklySchedule"]}
    # A finished export of the cycle (stored as failed so the POST in this test is not refused as a second export)
    fake.exports["export-1"] = {"id": "export-1", "tenantId": "org-1", "projectId": pid, "clusterId": cid,
                                "cycleId": "cycle-1", "bucketName": "orders", "status": "failed",
                                "createdAt": "2026-10-29T04:00:00Z", "_backup": backup, "_done_at": -1.0}
    return {"{organizationId}": "org-1", "{projectId}": pid, "{clusterId}": cid, "{bucketId}": bucket_id("orders"),
            "{scopeName}": "inventory", "{collectionName}": "items", "{allowedCidrId}": "cidr-1", "{userId}": "u-1",
            "free": fid, "free-bucket": bucket_id("free-b"), "snapshot": snap, "{backupId}": backup,
            "{cycleId}": "cycle-1", "{exportId}": "export-1"}


def _body(method: str, template: str, ids: dict[str, str]) -> dict[str, Any] | None:
    tail = template.rsplit("/", 1)[-1]
    if method not in ("POST", "PUT") or tail == "activationState":
        return None
    if tail == "cloudsnapshotbackupschedule":
        return {"interval": 12, "retention": 168, "startTime": "2026-10-30T02:00:00Z", "copyToRegions": []}
    if tail == "cloudsnapshotbackups":
        return {"retention": 168, "regionsToCopy": ["us-west-2"]}
    if tail == "{backupId}" and "cloudsnapshotbackups" in template:
        return {"retention": 2160}
    if tail == "restore" and "cloudsnapshotbackups" in template:
        return {}
    if tail == "restore":
        return {"targetClusterID": ids["{clusterId}"], "sourceClusterID": ids["{clusterId}"],
                "backupID": ids["{backupId}"], "services": ["data"]}
    if tail == "schedules":
        return BUCKET_SCHEDULE
    if tail in ("backups", "export"):
        return {}
    if tail == "projects":
        return {"name": "made", "description": "d"}
    if tail == "{projectId}":
        return {"name": "nova-dev", "description": "changed"}
    if tail == "clusters":
        return CLUSTER
    if tail == "freeTier" and "/buckets/" not in template:
        return {"name": "free-made", "cloudProvider": {"type": "aws", "region": "us-east-2", "cidr": "10.98.0.0/24"}}
    if tail == "{clusterId}" and "freeTier" in template:
        return {"name": "try-01", "description": "changed"}
    if tail == "{clusterId}":
        return {"name": "nova-dev-01", "description": "changed", "support": {"plan": "basic"},
                "serviceGroups": GROUPS}
    if tail == "deletionProtection":
        return {"enabled": True}
    if tail == "onOffSchedule":
        return SCHEDULE
    if tail == "allowedcidrs":
        return {"cidr": "198.51.100.0/24", "comment": "made"}
    if tail == "buckets" or (tail == "freeTier" and "/buckets/" in template):
        return {"name": "made", "memoryAllocationInMb": 128}
    if tail == "{bucketId}" and "freeTier" in template:
        return {"memoryAllocationInMb": 200}
    if tail == "{bucketId}":
        return {"memoryAllocationInMb": 1024, "durabilityLevel": "none", "replicas": 1, "flush": False,
                "timeToLiveInSeconds": 0}
    if tail == "scopes":
        return {"name": "made"}
    if tail == "collections":
        return {"name": "made", "maxTTL": 0}
    if tail == "{collectionName}":
        return {"maxTTL": 60}
    if tail == "users":
        return {"name": "made", "access": ACCESS}
    if tail == "{userId}":
        return {"access": ACCESS}
    return {}


def _path(template: str, ids: dict[str, str]) -> str:
    template = template.replace("/cloudsnapshotbackups/{backupId}", f"/cloudsnapshotbackups/{ids['snapshot']}")
    if "/clusters/freeTier/" in template:
        template = template.replace("/clusters/freeTier/{clusterId}", f"/clusters/freeTier/{ids['free']}")
    if "/buckets/freeTier/" in template:
        template = template.replace("/buckets/freeTier/{bucketId}", f"/buckets/freeTier/{ids['free-bucket']}")
    if "/buckets/freeTier" in template:
        template = template.replace("/clusters/{clusterId}", f"/clusters/{ids['free']}")
    for k, v in ids.items():
        if k.startswith("{"):
            template = template.replace(k, v)
    return template


def _order(op: tuple[str, str]) -> tuple[int, int]:
    """Reads and writes first, then deletes from the deepest resource up (a deleted parent hides its children)."""
    method, path = op
    return (1 if method == "DELETE" else 0, -path.count("/") if method == "DELETE" else 0)


@pytest.mark.story("CAP-004", "AC6")
def test_fake_ac6_response_shape_parity(fake, world):
    assert set(SPEC) == set(INVENTORY), "refresh the snapshot: python3 scripts/update-api-responses.py"
    report = []
    for method, template in sorted(INVENTORY, key=_order):
        spec = SPEC[(method, template)]
        assert spec["documented"], f"{method} {template} is not in the published spec"
        # Creates Capella allows only once: set the seeded one aside so the create gets the documented success.
        free_tier = fake.clusters.pop(world["free"]) if method == "POST" and template.endswith("/freeTier") \
            and "/buckets/" not in template else None
        if method == "POST" and template.endswith("/onOffSchedule"):
            fake.schedules.pop(world["{clusterId}"])
        if method == "POST" and template.endswith("/backup/schedules"):
            fake.bucket_backup_schedules.clear()
        if method == "DELETE" and template.endswith("/projects/{projectId}"):
            fake.clusters.clear()  # Capella deletes a project only once its clusters are gone
        r = requests.request(method, fake.base_url + _path(template, world), json=_body(method, template, world),
                             headers={"Authorization": "Bearer k-123456"}, timeout=5)
        if free_tier is not None:  # put the seeded free-tier cluster back for the calls that follow
            fake.clusters.pop(r.json().get("id", ""), None)
            fake.clusters[world["free"]] = free_tier
        documented = spec["responses"]
        if str(r.status_code) not in documented:
            report.append(f"{method} {template}: status {r.status_code} ({r.text[:120]}); the spec documents "
                          f"{', '.join(documented)}")
            continue
        schema = documented[str(r.status_code)]
        if schema is None:
            if r.text.strip():
                report.append(f"{method} {template}: a body, but the spec documents none")
            continue
        report += [f"{method} {template}: {p}" for p in problems(r.json(), schema, "body")]
    assert not report, "the fake differs from the Management API spec:\n" + "\n".join(report)


def test_fake_parity_checker_reports_each_kind():
    schema = {"type": "object", "required": ["id", "name"],
              "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "n": {"type": "integer"}}}
    found = problems({"id": 1, "n": True, "extra": "x"}, schema, "body")
    assert "body.name: required by the spec, missing in the fake" in found
    assert "body.id: int, the spec says string" in found
    assert "body.n: bool, the spec says integer" in found
    assert "body.extra: returned by the fake, not in the spec" in found
