"""One function per Management API v4.0 endpoint used in release 1.0.0 (CAP-003 AC9; backups: CAP-056–CAP-059).

Reference: https://docs.couchbase.com/cloud/management-api-reference/index.html
`get_*` functions return (body, etag). Update functions accept `if_match`.
"""

from __future__ import annotations

import re
from typing import Any

from capellactl.api.client import ApiResponse, CapellaClient

Body = dict[str, Any]


def _p(c: CapellaClient, project_id: str) -> str:
    return f"{c.org_path}/projects/{project_id}"


def _c(c: CapellaClient, project_id: str, cluster_id: str) -> str:
    return f"{_p(c, project_id)}/clusters/{cluster_id}"


def _b(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str) -> str:
    return f"{_c(c, project_id, cluster_id)}/buckets/{bucket_id}"


def _get(c: CapellaClient, path: str) -> tuple[Body, str | None]:
    r = c.get(path)
    return (r.body or {}), r.etag


# ----------------------------------------------------------- Organizations
def list_organizations(c: CapellaClient) -> list[Body]:
    """GET /v4/organizations  (#tag/Organizations)"""
    return c.paginate("/v4/organizations")


def get_organization(c: CapellaClient) -> tuple[Body, str | None]:
    """GET /v4/organizations/{organizationId}  (#tag/Organizations)"""
    return _get(c, c.org_path)


# ---------------------------------------------------------------- Projects
def list_projects(c: CapellaClient) -> list[Body]:
    """GET /v4/organizations/{organizationId}/projects  (#tag/Projects)"""
    return c.paginate(f"{c.org_path}/projects")


def get_project(c: CapellaClient, project_id: str) -> tuple[Body, str | None]:
    """GET …/projects/{projectId}  (#tag/Projects)"""
    return _get(c, _p(c, project_id))


def create_project(c: CapellaClient, body: Body) -> str:
    """POST …/projects → 201 {id}  (#tag/Projects)"""
    return str(c.post(f"{c.org_path}/projects", body).body["id"])


def update_project(c: CapellaClient, project_id: str, body: Body, if_match: str | None = None) -> None:
    """PUT …/projects/{projectId} → 204  (#tag/Projects)"""
    c.put(_p(c, project_id), body, if_match=if_match)


def delete_project(c: CapellaClient, project_id: str) -> None:
    """DELETE …/projects/{projectId} → 204 (409 when not empty)  (#tag/Projects)"""
    c.delete(_p(c, project_id))


# ---------------------------------------------------------------- Clusters
def list_clusters(c: CapellaClient, project_id: str) -> list[Body]:
    """GET …/projects/{projectId}/clusters  (#tag/Clusters)"""
    return c.paginate(f"{_p(c, project_id)}/clusters")


def get_cluster(c: CapellaClient, project_id: str, cluster_id: str) -> tuple[Body, str | None]:
    """GET …/clusters/{clusterId}  (#tag/Clusters)"""
    return _get(c, _c(c, project_id, cluster_id))


def create_cluster(c: CapellaClient, project_id: str, body: Body) -> str:
    """POST …/projects/{projectId}/clusters → 202 {id}  (#tag/Clusters)"""
    return str(c.post(f"{_p(c, project_id)}/clusters", body).body["id"])


def update_cluster(c: CapellaClient, project_id: str, cluster_id: str, body: Body, if_match: str | None = None) -> None:
    """PUT …/clusters/{clusterId} → 204  (#tag/Clusters)"""
    c.put(_c(c, project_id, cluster_id), body, if_match=if_match)


def delete_cluster(c: CapellaClient, project_id: str, cluster_id: str, retain_snapshot_backups: bool = True) -> None:
    """DELETE …/clusters/{clusterId}?retainsnapshotbackups= → 202  (#tag/Clusters)"""
    c.delete(_c(c, project_id, cluster_id), params={"retainsnapshotbackups": str(retain_snapshot_backups).lower()})


def set_deletion_protection(c: CapellaClient, project_id: str, cluster_id: str, enabled: bool) -> None:
    """PUT …/clusters/{clusterId}/deletionProtection → 204  (#tag/Clusters)"""
    c.put(f"{_c(c, project_id, cluster_id)}/deletionProtection", {"deletionProtection": enabled})


def turn_cluster_on(c: CapellaClient, project_id: str, cluster_id: str, with_app_service: bool = False) -> None:
    """POST …/clusters/{clusterId}/activationState → 202  (#tag/Clusters)"""
    c.post(f"{_c(c, project_id, cluster_id)}/activationState", {"turnOnLinkedAppService": with_app_service})


def turn_cluster_off(c: CapellaClient, project_id: str, cluster_id: str) -> None:
    """DELETE …/clusters/{clusterId}/activationState → 202  (#tag/Clusters)"""
    c.delete(f"{_c(c, project_id, cluster_id)}/activationState")


def turn_free_cluster_on(c: CapellaClient, project_id: str, cluster_id: str) -> None:
    """POST …/clusters/freeTier/{clusterId}/activationState → 202; also turns on linked App Services  (#tag/Free-Tier)"""
    c.post(f"{_p(c, project_id)}/clusters/freeTier/{cluster_id}/activationState", None)


def turn_free_cluster_off(c: CapellaClient, project_id: str, cluster_id: str) -> None:
    """DELETE …/clusters/freeTier/{clusterId}/activationState → 202  (#tag/Free-Tier)"""
    c.delete(f"{_p(c, project_id)}/clusters/freeTier/{cluster_id}/activationState")


def get_cluster_stats(c: CapellaClient, project_id: str, cluster_id: str) -> Body:
    """GET …/clusters/{clusterId}/stats → {freeMemoryInMb, totalMemoryInMb, maxReplicas}  (#tag/Clusters)"""
    return _get(c, f"{_c(c, project_id, cluster_id)}/stats")[0]


# ------------------------------------------------------- Free-tier clusters
def create_free_cluster(c: CapellaClient, project_id: str, body: Body) -> str:
    """POST …/clusters/freeTier → 202 {id}; one per organization  (#tag/Free-Tier)"""
    return str(c.post(f"{_p(c, project_id)}/clusters/freeTier", body).body["id"])


def get_free_cluster(c: CapellaClient, project_id: str, cluster_id: str) -> tuple[Body, str | None]:
    """GET …/clusters/freeTier/{clusterId}  (#tag/Free-Tier)"""
    return _get(c, f"{_p(c, project_id)}/clusters/freeTier/{cluster_id}")


def update_free_cluster(c: CapellaClient, project_id: str, cluster_id: str, body: Body,
                        if_match: str | None = None) -> None:
    """PUT …/clusters/freeTier/{clusterId} → 204; only name and description  (#tag/Free-Tier)"""
    c.put(f"{_p(c, project_id)}/clusters/freeTier/{cluster_id}", body, if_match=if_match)


def delete_free_cluster(c: CapellaClient, project_id: str, cluster_id: str) -> None:
    """DELETE …/clusters/freeTier/{clusterId} → 202  (#tag/Free-Tier)"""
    c.delete(f"{_p(c, project_id)}/clusters/freeTier/{cluster_id}")


# ---------------------------------------------------------- On/Off schedule
def get_schedule(c: CapellaClient, project_id: str, cluster_id: str) -> tuple[Body, str | None]:
    """GET …/clusters/{clusterId}/onOffSchedule (404 when none)  (#tag/On-Off-Schedule)"""
    return _get(c, f"{_c(c, project_id, cluster_id)}/onOffSchedule")


def create_schedule(c: CapellaClient, project_id: str, cluster_id: str, body: Body) -> None:
    """POST …/onOffSchedule → 204  (#tag/On-Off-Schedule)"""
    c.post(f"{_c(c, project_id, cluster_id)}/onOffSchedule", body)


def update_schedule(c: CapellaClient, project_id: str, cluster_id: str, body: Body, if_match: str | None = None) -> None:
    """PUT …/onOffSchedule → 204  (#tag/On-Off-Schedule)"""
    c.put(f"{_c(c, project_id, cluster_id)}/onOffSchedule", body, if_match=if_match)


def delete_schedule(c: CapellaClient, project_id: str, cluster_id: str) -> None:
    """DELETE …/onOffSchedule → 204  (#tag/On-Off-Schedule)"""
    c.delete(f"{_c(c, project_id, cluster_id)}/onOffSchedule")


def pause_schedule(c: CapellaClient, project_id: str, cluster_id: str) -> None:
    """DELETE …/onOffSchedule/activationState → 204  (#tag/On-Off-Schedule)"""
    c.delete(f"{_c(c, project_id, cluster_id)}/onOffSchedule/activationState")


def resume_schedule(c: CapellaClient, project_id: str, cluster_id: str) -> None:
    """POST …/onOffSchedule/activationState → 204  (#tag/On-Off-Schedule)"""
    c.post(f"{_c(c, project_id, cluster_id)}/onOffSchedule/activationState", {})


# ------------------------------------------------------------ Allowed CIDRs
def list_allowed_cidrs(c: CapellaClient, project_id: str, cluster_id: str) -> list[Body]:
    """GET …/clusters/{clusterId}/allowedcidrs  (#tag/Allowed-CIDRs-(Cluster))"""
    return c.paginate(f"{_c(c, project_id, cluster_id)}/allowedcidrs")


def get_allowed_cidr(c: CapellaClient, project_id: str, cluster_id: str, cidr_id: str) -> tuple[Body, str | None]:
    """GET …/allowedcidrs/{allowedCidrId}  (#tag/Allowed-CIDRs-(Cluster))"""
    return _get(c, f"{_c(c, project_id, cluster_id)}/allowedcidrs/{cidr_id}")


def create_allowed_cidr(c: CapellaClient, project_id: str, cluster_id: str, body: Body) -> str:
    """POST …/allowedcidrs → 201 {id}  (#tag/Allowed-CIDRs-(Cluster))"""
    return str(c.post(f"{_c(c, project_id, cluster_id)}/allowedcidrs", body).body["id"])


def delete_allowed_cidr(c: CapellaClient, project_id: str, cluster_id: str, cidr_id: str) -> None:
    """DELETE …/allowedcidrs/{allowedCidrId} → 204  (#tag/Allowed-CIDRs-(Cluster))"""
    c.delete(f"{_c(c, project_id, cluster_id)}/allowedcidrs/{cidr_id}")


# ----------------------------------------------------------------- Buckets
def list_buckets(c: CapellaClient, project_id: str, cluster_id: str) -> list[Body]:
    """GET …/clusters/{clusterId}/buckets  (#tag/Buckets-Scopes-and-Collections)"""
    return c.paginate(f"{_c(c, project_id, cluster_id)}/buckets")


def get_bucket(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str) -> tuple[Body, str | None]:
    """GET …/buckets/{bucketId}"""
    return _get(c, _b(c, project_id, cluster_id, bucket_id))


def create_bucket(c: CapellaClient, project_id: str, cluster_id: str, body: Body) -> str:
    """POST …/buckets → 201 {id}"""
    return str(c.post(f"{_c(c, project_id, cluster_id)}/buckets", body).body["id"])


def update_bucket(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, body: Body) -> None:
    """PUT …/buckets/{bucketId} → 204"""
    c.put(_b(c, project_id, cluster_id, bucket_id), body)


def delete_bucket(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str) -> None:
    """DELETE …/buckets/{bucketId} → 204"""
    c.delete(_b(c, project_id, cluster_id, bucket_id))


# ------------------------------------------------------ Free-tier buckets
def _fb(c: CapellaClient, project_id: str, cluster_id: str) -> str:
    return f"{_c(c, project_id, cluster_id)}/buckets/freeTier"


def list_free_buckets(c: CapellaClient, project_id: str, cluster_id: str) -> tuple[list[Body], Body]:
    """GET …/buckets/freeTier → {data, clusterStats} (not paginated)  (#tag/Free-Tier)"""
    body = c.get(_fb(c, project_id, cluster_id)).body or {}
    return list(body.get("data") or []), dict(body.get("clusterStats") or {})


def get_free_bucket(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str) -> tuple[Body, str | None]:
    """GET …/buckets/freeTier/{bucketId}  (#tag/Free-Tier)"""
    return _get(c, f"{_fb(c, project_id, cluster_id)}/{bucket_id}")


def create_free_bucket(c: CapellaClient, project_id: str, cluster_id: str, body: Body) -> str:
    """POST …/buckets/freeTier → 201 {id}; only name and memoryAllocationInMb  (#tag/Free-Tier)"""
    return str(c.post(_fb(c, project_id, cluster_id), body).body["id"])


def update_free_bucket(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, body: Body) -> None:
    """PUT …/buckets/freeTier/{bucketId} → 204; memoryAllocationInMb*, enableCrossClusterVersioning  (#tag/Free-Tier)"""
    c.put(f"{_fb(c, project_id, cluster_id)}/{bucket_id}", body)


def delete_free_bucket(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str) -> None:
    """DELETE …/buckets/freeTier/{bucketId} → 204  (#tag/Free-Tier)"""
    c.delete(f"{_fb(c, project_id, cluster_id)}/{bucket_id}")


# ------------------------------------------------------------------ Scopes
def list_scopes(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str) -> list[Body]:
    """GET …/buckets/{bucketId}/scopes → {scopes: [...]}"""
    return c.paginate(f"{_b(c, project_id, cluster_id, bucket_id)}/scopes", key="scopes")


def get_scope(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, scope: str) -> tuple[Body, str | None]:
    """GET …/scopes/{scopeName}"""
    return _get(c, f"{_b(c, project_id, cluster_id, bucket_id)}/scopes/{scope}")


def create_scope(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, name: str) -> None:
    """POST …/scopes → 201"""
    c.post(f"{_b(c, project_id, cluster_id, bucket_id)}/scopes", {"name": name})


def delete_scope(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, scope: str) -> None:
    """DELETE …/scopes/{scopeName} → 204"""
    c.delete(f"{_b(c, project_id, cluster_id, bucket_id)}/scopes/{scope}")


# ------------------------------------------------------------- Collections
def _coll(c: CapellaClient, p: str, cl: str, b: str, s: str) -> str:
    return f"{_b(c, p, cl, b)}/scopes/{s}/collections"


def list_collections(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, scope: str) -> list[Body]:
    """GET …/scopes/{scopeName}/collections"""
    return c.paginate(_coll(c, project_id, cluster_id, bucket_id, scope))


def get_collection(
    c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, scope: str, name: str
) -> tuple[Body, str | None]:
    """GET …/collections/{collectionName}"""
    return _get(c, f"{_coll(c, project_id, cluster_id, bucket_id, scope)}/{name}")


def create_collection(
    c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, scope: str, body: Body
) -> None:
    """POST …/collections → 201"""
    c.post(_coll(c, project_id, cluster_id, bucket_id, scope), body)


def update_collection(
    c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, scope: str, name: str, max_ttl: int,
    if_match: str | None = None,
) -> None:
    """PUT …/collections/{collectionName} → 204 (server >= 7.6.0)"""
    c.put(f"{_coll(c, project_id, cluster_id, bucket_id, scope)}/{name}", {"maxTTL": max_ttl}, if_match=if_match)


def delete_collection(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, scope: str, name: str) -> None:
    """DELETE …/collections/{collectionName} → 204"""
    c.delete(f"{_coll(c, project_id, cluster_id, bucket_id, scope)}/{name}")


# ---------------------------------------------------- Database credentials
def list_credentials(c: CapellaClient, project_id: str, cluster_id: str) -> list[Body]:
    """GET …/clusters/{clusterId}/users  (#tag/Database-Credentials)"""
    return c.paginate(f"{_c(c, project_id, cluster_id)}/users")


def get_credential(c: CapellaClient, project_id: str, cluster_id: str, user_id: str) -> tuple[Body, str | None]:
    """GET …/users/{userId} (never returns the password)"""
    return _get(c, f"{_c(c, project_id, cluster_id)}/users/{user_id}")


def create_credential(c: CapellaClient, project_id: str, cluster_id: str, body: Body) -> tuple[str, str]:
    """POST …/users → 201 {id, password}. The password is returned only here."""
    r: ApiResponse = c.post(f"{_c(c, project_id, cluster_id)}/users", body)
    return str(r.body["id"]), str(r.body["password"])


def update_credential(
    c: CapellaClient, project_id: str, cluster_id: str, user_id: str, body: Body, if_match: str | None = None
) -> None:
    """PUT …/users/{userId} → 204"""
    c.put(f"{_c(c, project_id, cluster_id)}/users/{user_id}", body, if_match=if_match)


def delete_credential(c: CapellaClient, project_id: str, cluster_id: str, user_id: str) -> None:
    """DELETE …/users/{userId} → 204"""
    c.delete(f"{_c(c, project_id, cluster_id)}/users/{user_id}")


# ------------------------------------ Cloud snapshot backups (cluster backups, CAP-056, CAP-057)
def _cs(c: CapellaClient, project_id: str, cluster_id: str) -> str:
    return f"{_c(c, project_id, cluster_id)}/cloudsnapshotbackups"


def get_snapshot_schedule(c: CapellaClient, project_id: str, cluster_id: str) -> Body | None:
    """GET …/cloudsnapshotbackupschedule → 200, or 204 when there is none (None)  (#tag/Cloud-Snapshot-Backups-Schedule)"""
    body = c.get(f"{_c(c, project_id, cluster_id)}/cloudsnapshotbackupschedule").body
    return body or None


def upsert_snapshot_schedule(c: CapellaClient, project_id: str, cluster_id: str, body: Body) -> None:
    """PUT …/cloudsnapshotbackupschedule → 204 (creates or replaces)"""
    c.put(f"{_c(c, project_id, cluster_id)}/cloudsnapshotbackupschedule", body)


def delete_snapshot_schedule(c: CapellaClient, project_id: str, cluster_id: str) -> None:
    """DELETE …/cloudsnapshotbackupschedule → 204"""
    c.delete(f"{_c(c, project_id, cluster_id)}/cloudsnapshotbackupschedule")


def get_snapshot_schedule_options(c: CapellaClient, project_id: str, cluster_id: str) -> Body:
    """GET …/cloudsnapshotbackupschedule/options → {intervals, minimumRetention, maximumRetention} (hours)"""
    return dict(c.get(f"{_c(c, project_id, cluster_id)}/cloudsnapshotbackupschedule/options").body or {})


def list_snapshot_regions(c: CapellaClient, project_id: str, cluster_id: str) -> list[str]:
    """GET …/cloudsnapshotbackups/regions → [region] (AWS and Azure only)"""
    body = c.get(f"{_cs(c, project_id, cluster_id)}/regions").body
    return [str(r) for r in body] if isinstance(body, list) else []


def list_snapshots(c: CapellaClient, project_id: str, cluster_id: str) -> list[Body]:
    """GET …/clusters/{clusterId}/cloudsnapshotbackups (paginated; queued backups are not listed)"""
    return c.paginate(_cs(c, project_id, cluster_id))


def list_project_snapshots(c: CapellaClient, project_id: str) -> list[Body]:
    """GET …/projects/{projectId}/cloudsnapshotbackups → one summary per cluster (most recent, oldest)"""
    return c.paginate(f"{_p(c, project_id)}/cloudsnapshotbackups")


def create_snapshot(c: CapellaClient, project_id: str, cluster_id: str, body: Body) -> str:
    """POST …/cloudsnapshotbackups → 202 {backupId}; optional retention (hours), regionsToCopy (at most two)"""
    return str((c.post(_cs(c, project_id, cluster_id), body).body or {}).get("backupId", ""))


def update_snapshot_retention(c: CapellaClient, project_id: str, cluster_id: str, backup_id: str, retention: int) -> None:
    """PUT …/cloudsnapshotbackups/{backupId} → 204 {retention} (hours)"""
    c.put(f"{_cs(c, project_id, cluster_id)}/{backup_id}", {"retention": retention})


def delete_snapshot(c: CapellaClient, project_id: str, cluster_id: str, backup_id: str) -> None:
    """DELETE …/cloudsnapshotbackups/{backupId} → 202"""
    c.delete(f"{_cs(c, project_id, cluster_id)}/{backup_id}")


def restore_snapshot(c: CapellaClient, project_id: str, cluster_id: str, backup_id: str, body: Body) -> str:
    """POST …/cloudsnapshotbackups/{backupId}/restore → 202 {restoreId}; replaces all data of the cluster"""
    return str((c.post(f"{_cs(c, project_id, cluster_id)}/{backup_id}/restore", body).body or {}).get("restoreId", ""))


def list_snapshot_restores(c: CapellaClient, project_id: str, cluster_id: str) -> list[Body]:
    """GET …/cloudsnapshotbackups/restores (paginated)"""
    return c.paginate(f"{_cs(c, project_id, cluster_id)}/restores")


# ---------------------------------------------- Bucket backups (CAP-058, CAP-059)
def get_bucket_backup_schedule(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str) -> Body:
    """GET …/buckets/{bucketId}/backup/schedules (404 when none)  (#tag/Backup-Schedule-(Bucket))"""
    return dict(c.get(f"{_b(c, project_id, cluster_id, bucket_id)}/backup/schedules").body or {})


def create_bucket_backup_schedule(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, body: Body) -> None:
    """POST …/backup/schedules → 202 {type: weekly, weeklySchedule}"""
    c.post(f"{_b(c, project_id, cluster_id, bucket_id)}/backup/schedules", body)


def update_bucket_backup_schedule(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, body: Body) -> None:
    """PUT …/backup/schedules → 204"""
    c.put(f"{_b(c, project_id, cluster_id, bucket_id)}/backup/schedules", body)


def delete_bucket_backup_schedule(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str) -> None:
    """DELETE …/backup/schedules → 202"""
    c.delete(f"{_b(c, project_id, cluster_id, bucket_id)}/backup/schedules")


def list_backup_cycles(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str) -> list[Body]:
    """GET …/backup/cycles → {data: [{cycleID, createdAt}]}"""
    return list((c.get(f"{_b(c, project_id, cluster_id, bucket_id)}/backup/cycles").body or {}).get("data") or [])


def list_cycle_backups(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, cycle_id: str) -> list[Body]:
    """GET …/backup/cycles/{cycleId} → {data: [backup]}"""
    path = f"{_b(c, project_id, cluster_id, bucket_id)}/backup/cycles/{cycle_id}"
    return list((c.get(path).body or {}).get("data") or [])


def create_bucket_backup(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str) -> None:
    """POST …/buckets/{bucketId}/backups → 202, no body: the new backup is found by listing  (#tag/Backups-and-Restore-(Bucket))"""
    c.post(f"{_b(c, project_id, cluster_id, bucket_id)}/backups", {})


def list_cluster_backups(c: CapellaClient, project_id: str, cluster_id: str) -> list[Body]:
    """GET …/clusters/{clusterId}/backups → {data}: the latest backup of each bucket (queued ones are not listed)"""
    return list((c.get(f"{_c(c, project_id, cluster_id)}/backups").body or {}).get("data") or [])


def get_backup(c: CapellaClient, project_id: str, cluster_id: str, backup_id: str) -> Body:
    """GET …/clusters/{clusterId}/backups/{backupId}"""
    return dict(c.get(f"{_c(c, project_id, cluster_id)}/backups/{backup_id}").body or {})


def delete_backup(c: CapellaClient, project_id: str, cluster_id: str, backup_id: str) -> None:
    """DELETE …/backups/{backupId} → 202: deletes every backup of the backup's cycle"""
    c.delete(f"{_c(c, project_id, cluster_id)}/backups/{backup_id}")


def restore_backup(c: CapellaClient, project_id: str, cluster_id: str, backup_id: str, body: Body) -> None:
    """POST …/backups/{backupId}/restore → 202; targetClusterID, sourceClusterID, backupID and services required"""
    c.post(f"{_c(c, project_id, cluster_id)}/backups/{backup_id}/restore", body)


def export_backup(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, backup_id: str) -> str:
    """POST …/buckets/{bucketId}/backups/{backupId}/export → 202 {exportId}; 409 when the cycle has one already"""
    path = f"{_b(c, project_id, cluster_id, bucket_id)}/backups/{backup_id}/export"
    return str((c.post(path, {}).body or {}).get("exportId", ""))


def get_backup_export(c: CapellaClient, project_id: str, cluster_id: str, bucket_id: str, backup_id: str,
                      export_id: str) -> Body:
    """GET …/backups/{backupId}/exports/{exportId} → status; backupDownloadURL once complete (valid 1 hour)"""
    return dict(c.get(f"{_b(c, project_id, cluster_id, bucket_id)}/backups/{backup_id}/exports/{export_id}").body or {})


# ------------------------------------------------------- Endpoint inventory
# (method, path template) for every endpoint above. Used by tests and the fake harness (CAP-004 AC1).
_ORG = "/v4/organizations/{organizationId}"
_PRJ = _ORG + "/projects/{projectId}"
_CLU = _PRJ + "/clusters/{clusterId}"
_BKT = _CLU + "/buckets/{bucketId}"
INVENTORY: list[tuple[str, str]] = [
    ("GET", "/v4/organizations"), ("GET", _ORG),
    ("GET", _ORG + "/projects"), ("POST", _ORG + "/projects"), ("GET", _PRJ), ("PUT", _PRJ), ("DELETE", _PRJ),
    ("GET", _PRJ + "/clusters"), ("POST", _PRJ + "/clusters"), ("GET", _CLU), ("PUT", _CLU), ("DELETE", _CLU),
    ("PUT", _CLU + "/deletionProtection"), ("POST", _CLU + "/activationState"), ("DELETE", _CLU + "/activationState"),
    ("GET", _CLU + "/stats"),
    ("POST", _PRJ + "/clusters/freeTier"), ("GET", _PRJ + "/clusters/freeTier/{clusterId}"),
    ("PUT", _PRJ + "/clusters/freeTier/{clusterId}"), ("DELETE", _PRJ + "/clusters/freeTier/{clusterId}"),
    ("POST", _PRJ + "/clusters/freeTier/{clusterId}/activationState"),
    ("DELETE", _PRJ + "/clusters/freeTier/{clusterId}/activationState"),
    ("GET", _CLU + "/onOffSchedule"), ("POST", _CLU + "/onOffSchedule"), ("PUT", _CLU + "/onOffSchedule"),
    ("DELETE", _CLU + "/onOffSchedule"), ("POST", _CLU + "/onOffSchedule/activationState"),
    ("DELETE", _CLU + "/onOffSchedule/activationState"),
    ("GET", _CLU + "/allowedcidrs"), ("POST", _CLU + "/allowedcidrs"), ("GET", _CLU + "/allowedcidrs/{allowedCidrId}"),
    ("DELETE", _CLU + "/allowedcidrs/{allowedCidrId}"),
    ("GET", _CLU + "/buckets"), ("POST", _CLU + "/buckets"), ("GET", _BKT), ("PUT", _BKT), ("DELETE", _BKT),
    ("GET", _CLU + "/buckets/freeTier"), ("POST", _CLU + "/buckets/freeTier"),
    ("GET", _CLU + "/buckets/freeTier/{bucketId}"), ("PUT", _CLU + "/buckets/freeTier/{bucketId}"),
    ("DELETE", _CLU + "/buckets/freeTier/{bucketId}"),
    ("GET", _BKT + "/scopes"), ("POST", _BKT + "/scopes"), ("GET", _BKT + "/scopes/{scopeName}"),
    ("DELETE", _BKT + "/scopes/{scopeName}"),
    ("GET", _BKT + "/scopes/{scopeName}/collections"), ("POST", _BKT + "/scopes/{scopeName}/collections"),
    ("GET", _BKT + "/scopes/{scopeName}/collections/{collectionName}"),
    ("PUT", _BKT + "/scopes/{scopeName}/collections/{collectionName}"),
    ("DELETE", _BKT + "/scopes/{scopeName}/collections/{collectionName}"),
    ("GET", _CLU + "/users"), ("POST", _CLU + "/users"), ("GET", _CLU + "/users/{userId}"), ("PUT", _CLU + "/users/{userId}"),
    ("DELETE", _CLU + "/users/{userId}"),
    ("GET", _CLU + "/cloudsnapshotbackupschedule"), ("PUT", _CLU + "/cloudsnapshotbackupschedule"),
    ("DELETE", _CLU + "/cloudsnapshotbackupschedule"), ("GET", _CLU + "/cloudsnapshotbackupschedule/options"),
    ("GET", _CLU + "/cloudsnapshotbackups/regions"), ("GET", _CLU + "/cloudsnapshotbackups"),
    ("GET", _PRJ + "/cloudsnapshotbackups"), ("POST", _CLU + "/cloudsnapshotbackups"),
    ("PUT", _CLU + "/cloudsnapshotbackups/{backupId}"), ("DELETE", _CLU + "/cloudsnapshotbackups/{backupId}"),
    ("POST", _CLU + "/cloudsnapshotbackups/{backupId}/restore"), ("GET", _CLU + "/cloudsnapshotbackups/restores"),
    ("GET", _BKT + "/backup/schedules"), ("POST", _BKT + "/backup/schedules"), ("PUT", _BKT + "/backup/schedules"),
    ("DELETE", _BKT + "/backup/schedules"), ("GET", _BKT + "/backup/cycles"), ("GET", _BKT + "/backup/cycles/{cycleId}"),
    ("POST", _BKT + "/backups"), ("GET", _CLU + "/backups"), ("GET", _CLU + "/backups/{backupId}"),
    ("DELETE", _CLU + "/backups/{backupId}"), ("POST", _CLU + "/backups/{backupId}/restore"),
    ("POST", _BKT + "/backups/{backupId}/export"), ("GET", _BKT + "/backups/{backupId}/exports/{exportId}"),
]

# Roles needed per endpoint, from the API reference, for 403 messages (CAP-003 AC2).
_ROLES: list[tuple[str, str, str]] = [
    ("POST", r"^/v4/organizations/[^/]+/projects$", "Organization Owner or Project Creator"),
    ("PUT", r"^/v4/organizations/[^/]+/projects/[^/]+$", "Organization Owner or Project Owner"),
    ("DELETE", r"^/v4/organizations/[^/]+/projects/[^/]+$", "Organization Owner or Project Owner"),
    ("GET", r"^/v4/organizations(/[^/]+)?(/projects)?$", "any organization role (Organization Member or above)"),
    # Backups (spec): bucket backup schedules and snapshot schedule options also allow Project Manager; the rest not
    ("*", r"/(buckets/[^/]+/backup/schedules|cloudsnapshotbackupschedule/options)$",
     "Organization Owner, Project Owner or Project Manager"),
    ("*", r"/(cloudsnapshotbackups?|cloudsnapshotbackupschedule|backups?)(/|$)", "Organization Owner or Project Owner"),
    ("*", r"/clusters", "Organization Owner, Project Owner or Project Manager"),
]


def required_roles(method: str, path: str) -> str | None:
    for m, pattern, roles in _ROLES:
        if m in ("*", method.upper()) and re.search(pattern, path):
            return roles
    return None
