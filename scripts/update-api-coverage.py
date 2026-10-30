#!/usr/bin/env python3
"""Generate the Management API coverage reports.

  docs/release-1.0.0/API-COVERAGE.md                operational database (release 1.0.0)
  docs/release-1.5.0/API-COVERAGE.md                the rest of the operational database (release 1.5.0)
  docs/release-2.0.0/API-COVERAGE-APP-SERVICES.md   App Services and App Endpoints (release 2.0.0)

Inputs: the operation list of the Management API spec (docs/api/management-api-v4.0-operations.json, an offline
snapshot so CI needs no network), the command dictionary below, and the **Status** of each story file
(docs/release-*/CAP-*.md; a story's release is its directory). A command's status is derived from its stories
(all Implemented: done; some: partial; none: not built), and an operation's status from its commands. In a
release's report, stories of a later release don't count: their operations show as not in that release. Marking a
story Implemented and re-running this script is enough to update the reports; never edit them by hand.

Usage:
  python3 scripts/update-api-coverage.py            write the reports
  python3 scripts/update-api-coverage.py --check    exit 1 when a report is stale (CI)
  python3 scripts/update-api-coverage.py --refresh-spec [URL]
                                                    re-download the spec into the snapshot (needs network and
                                                    PyYAML), then write the reports; fails on unmapped operations
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "docs" / "api" / "management-api-v4.0-operations.json"
REL10, REL15 = "1.0.0", "1.5.0"
STORY_DIRS = [ROOT / "docs" / f"release-{r}" for r in (REL10, REL15)]
OUT_DB = ROOT / "docs" / "release-1.0.0" / "API-COVERAGE.md"
OUT_15 = ROOT / "docs" / "release-1.5.0" / "API-COVERAGE.md"
OUT_AS = ROOT / "docs" / "release-2.0.0" / "API-COVERAGE-APP-SERVICES.md"
SPEC_URL = "https://docs.couchbase.com/cloud/management-api-reference/_attachments/openapi.external.generated.yaml"
REF = "https://docs.couchbase.com/cloud/management-api-reference/index.html#tag/"

ORG = "/v4/organizations/{organizationId}"
PRJ = ORG + "/projects/{projectId}"
CLU = PRJ + "/clusters/{clusterId}"
FT = PRJ + "/clusters/freeTier/{clusterId}"
BKT = CLU + "/buckets/{bucketId}"
FB = CLU + "/buckets/freeTier"

DONE, PART, TODO, NONE, LATER = "✅ Done", "🟡 Partial", "⬜ Not built", "➖ Not needed", "⏭️ Not in 1.0"
ORDER = [DONE, PART, TODO, NONE, LATER]
NO_STORY = "none"  # requirement with no story yet (a gap): never counts as implemented

# ======================================================================== command dictionary
# name: (stories, what's left while not done). No stories: in no release yet (a proposed name).
COMMANDS: dict[str, tuple[tuple[str, ...], str]] = {}


def cmd(name: str, stories: str = "", left: str = "") -> None:
    COMMANDS[name] = (tuple(s.strip() for s in stories.split(",") if s.strip()), left)


for n in ("project list", "project get", "project create"):
    cmd(n, "CAP-009, CAP-039")
cmd("project update", "CAP-009, CAP-039")
cmd("project delete", "CAP-010")
cmd("cluster options", "CAP-041")
cmd("cluster list", "CAP-038")
cmd("cluster get", "CAP-038, CAP-041")
cmd("cluster create", "CAP-011, CAP-038, CAP-041, CAP-051, CAP-053, CAP-060",
    "Multi-dimensional service groups (`--group SPEC`, CAP-051); `--server-version`, `--single-node`, `--zone`, "
    "`--cmek-id`, `--private-dns`, `--disk-auto-expansion` (CAP-053); disk type picker and size-based IOPS (CAP-060).")
cmd("cluster update", "CAP-012, CAP-017, CAP-053, CAP-060", "Lowering RAM runs the CAP-016 memory guard (CAP-017 AC6); "
    "`--disk-auto-expansion` on Azure (CAP-053); `--disk-type` (CAP-060).")
cmd("cluster scale", "CAP-015, CAP-016, CAP-018",
    "Scale out and in (capacity checks); `--step ±1` within `--min/--max`, `--all-groups`.")
cmd("cluster group list", "CAP-052", "Service groups with nodes, compute and disk.")
cmd("cluster group add", "CAP-052, CAP-060", "Adds a service group; size defaults to the data group; disk type picker "
    "(CAP-060).")
cmd("cluster group remove", "CAP-052", "Removes a service group with the CAP-016 scale-in guards.")
cmd("cluster clone", "CAP-049", "Copies size, services, buckets, scopes and collections to another region; "
    "`--with-cidrs`, `--with-credentials` (new passwords).")
cmd("cluster delete", "CAP-014, CAP-041")
cmd("cluster protect", "CAP-013")
cmd("cluster power on", "CAP-019", "Waits until healthy; `--with-app-service`; `apply --power-on`.")
cmd("cluster power off", "CAP-019", "Waits until turned off; shows when the schedule turns it on again.")
cmd("cluster schedule show", "CAP-020", "Weekly grid and next transition.")
cmd("cluster schedule set", "CAP-020", "Records the schedule in capella.yaml and applies it.")
cmd("cluster schedule apply", "CAP-020")
cmd("cluster schedule delete", "CAP-020", "Also removes `hibernation` from capella.yaml.")
for a in ("pause", "resume"):
    cmd(f"cluster schedule {a}", "CAP-021", "Records `paused` in capella.yaml.")
for n in ("cidr list", "cidr create", "cidr delete"):
    cmd(n, "CAP-022")
for n in ("bucket list", "bucket get", "bucket create", "bucket update"):
    cmd(n, "CAP-023, CAP-041")
cmd("bucket delete", "CAP-024, CAP-041")
for n in ("scope list", "scope create"):
    cmd(n, "CAP-025")
cmd("scope delete", "CAP-026")
for n in ("collection list", "collection create", "collection update"):
    cmd(n, "CAP-025")
cmd("collection delete", "CAP-026")
cmd("credential list", "CAP-046")
cmd("credential get", "CAP-046")
cmd("credential create", "CAP-027, CAP-046")
cmd("credential update", "CAP-027, CAP-028, CAP-046")
cmd("credential delete", "CAP-029")
for n in ("show", "options", "set", "delete"):
    cmd(f"cluster backup schedule {n}", "CAP-056", "Cloud snapshot schedule; `backupSchedule` in capella.yaml.")
for n in ("list", "create", "retain", "delete", "restore", "restores", "regions"):
    cmd(f"cluster backup {n}", "CAP-057", "Cloud snapshot backups of the whole cluster.")
for n in ("show", "set", "delete"):
    cmd(f"bucket backup schedule {n}", "CAP-058", "Weekly full + incremental; `backupSchedule` under the bucket.")
for n in ("list", "get"):
    cmd(f"bucket backup cycle {n}", "CAP-058")
for n in ("list", "get", "create", "delete", "restore", "export"):
    cmd(f"bucket backup {n}", "CAP-059", "Bucket backups; `delete` removes the whole cycle.")

# Release 1.5.0: the rest of the operational database. (group, verbs, stories, what's left).
RELEASE_15 = [
    ("db-role", "privileges|list|get|create|update|delete", "CAP-064",
     "Custom roles in capella.yaml; `credential create/update --role` sends `userRoles`."),
    ("sample-bucket", "load|list|get|delete", "CAP-065", "Imperative; samples are not drift."),
    ("bucket", "flush", "CAP-066", "Typed confirmation; needs `flush: true` on the bucket."),
    ("index", "create|drop|build|list|get|status", "CAP-067",
     "`indexes` under a collection; changed keys are a replace; deferred create + one build."),
    ("eventing", "list|get|create|update|delete|code get|code set|state|logs", "CAP-068",
     "`eventingFunctions` with code from files; pause/resume around changes."),
    ("data-api", "show|update|endpoint-command|endpoint list|endpoint accept|endpoint reject", "CAP-069",
     "`dataApi` block; private endpoints accepted from the CLI."),
    ("replication", "list|get|create|update|delete|pause|resume|job", "CAP-070",
     "`replications` under the source cluster; deleted before their buckets."),
    ("cluster backup", "clone", "CAP-071", "New cluster from a snapshot backup."),
    ("cluster", "migrate-buckets", "CAP-072", "Couchstore ↔ Magma."),
    ("cluster", "certificate", "CAP-073", "Prints or saves the CA certificate."),
    ("peer", "create|list|get|delete|azure-command", "CAP-074", "`networkPeers`; a change is a replace."),
    ("private-endpoint", "show|enable|update|disable|list|command|accept|reject", "CAP-075",
     "`privateEndpointService` with routes and accepted endpoints."),
    ("audit-log", "get|update|events|export create|export list|export get", "CAP-076",
     "`auditLog` by event, name or module; exports downloaded."),
    ("cmek", "accounts|azure-app|create|list|get|history|rotate|delete|enable-provider|associate|unassociate", "CAP-077",
     "Organization and Azure project keys; rotation, never pruned."),
    ("org", "update", "CAP-078", "Subdomain, with `If-Match`."),
    ("user", "list|get|create|update|delete", "CAP-079", "Organization and project roles; imperative."),
    ("apikey", "list|get|create|delete|rotate", "CAP-080", "Token stored in a profile, a file or shown once."),
    ("alert", "create|list|channels|get|update|delete|test", "CAP-081",
     "`alertIntegrations` per project; secrets only as `${env:…}`."),
    ("event", "list|get", "CAP-082", "Filters, pagination and `--follow`."),
    ("billing", "get|prepaid|payg|download", "CAP-083", "Categorized and itemized reports."),
    ("insights", "list|get|create|update|delete|power on|power off", "CAP-084",
     "`insightsClusters` per project."),
    ("insights schedule", "show|set|delete", "CAP-085", "Same model as `cluster schedule` (CAP-020)."),
    ("insights cidr", "list|get|create|delete", "CAP-086", "Same model as `cidr` (CAP-022)."),
    ("insights backup", "list|create|retain|delete|restore|restores|schedule show|schedule set|schedule delete",
     "CAP-087", "Same model as `cluster backup` (CAP-056, CAP-057)."),
    ("insights private-endpoint", "show|enable|disable|command|list|accept|reject", "CAP-088",
     "Same model as `private-endpoint` (CAP-075)."),
]
for _group, _verbs, _stories, _left in RELEASE_15:
    for _v in _verbs.split("|"):
        cmd(f"{_group} {_v}", _stories, _left)

# Workflow commands: not one-to-one with an API operation. (name, stories, note)
WORKFLOW = [
    ("configure", "CAP-037, CAP-047", "Saves a profile and stores the API key in the OS keychain. Calls `GET /v4/organizations`; "
                                      "with an existing capella.yaml, also `GET …/projects` to check it (CAP-047)."),
    ("configure list / show / remove", "CAP-037", "No API calls."),
    ("init", "CAP-035", "Wizard that writes capella.yaml."),
    ("import", "CAP-036, CAP-047, CAP-048, CAP-054", "Hidden alias of `sync` since CAP-054. Reads projects, clusters, CIDRs, "
                                                "buckets, scopes, schedules and credentials into capella.yaml."),
    ("validate", "CAP-002", "Offline check of schema, references and password rules."),
    ("plan", "CAP-005, CAP-048", "Diffs projects, clusters, deletion protection, schedules, CIDRs, buckets, scopes, "
                                 "collections and credentials."),
    ("apply", "CAP-006, CAP-016, CAP-019, CAP-031", "Same coverage as `plan`; `--prune`, `--rotate-passwords`, "
                                                    "`--power-on` and the scale-in flags."),
    ("sync", "CAP-038, CAP-048, CAP-054", "Refreshes capella.yaml from Capella; with CAP-054 it covers every "
                                    "project in the organization and `import` becomes its alias."),
    ("destroy", "CAP-030", "Deletes every declared resource in reverse order; capella.yaml is kept."),
    ("drift", "CAP-031", "Read-only: changed, missing and unmanaged resources; `--detailed-exitcode`."),
    ("help / completion", "CAP-034", "No API calls."),
    ("cluster disk-types", "CAP-060", "No API calls: disk types, sizes and IOPS from `config/disks.yaml` (Capella's "
                                      "documentation; the spec has only the type names)."),
]

# ======================================================================== operation map
# (METHOD, path) -> dict(commands, status, note, left, requires, partial_use)
#   commands     capellactl command(s) that call it (" / " separated), or an "internal: …" description
#   status       explicit status for internal-only or not-needed operations; otherwise derived
#   note         always shown;  left: shown while not done
#   stories      the stories that deliver this operation, when not all of its commands' stories do (for example
#                the free-tier paths of `cluster update`, delivered by CAP-041 alone)
#   requires     extra stories (NO_STORY for a gap) the operation needs beyond its commands' stories
#   partial_use  already used read-only somewhere (import, guards): not built becomes partial
OPS: dict[tuple[str, str], dict[str, Any]] = {}


def _ids(text: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in text.split(",") if s.strip())


def op(method: str, path: str, commands: str, note: str = "", left: str = "", status: str | None = None,
       stories: str = "", requires: str = "", partial_use: bool = False) -> None:
    OPS[(method, path)] = {"commands": commands, "note": note, "left": left, "status": status,
                           "stories": _ids(stories), "requires": _ids(requires), "partial_use": partial_use}


# Organizations
op("GET", "/v4/organizations", "internal: `configure`, `init` (organization picker)",
   "No `org list` command; the organization is chosen once per profile.", status=DONE)
op("GET", ORG, "internal: `validate`, `plan`, `sync`, `project get`",
   "Confirms that the organization exists and is reachable.", status=DONE)
op("PUT", ORG + "/configuration", "org update")
# Projects
op("GET", ORG + "/projects", "project list")
op("POST", ORG + "/projects", "project create")
op("GET", PRJ, "project get")
op("PUT", PRJ, "project update", "CLI changes the description; a rename goes through capella.yaml and `apply`.")
op("DELETE", PRJ, "project delete", "`--cascade` deletes the project's clusters first.")
# Clusters
op("GET", PRJ + "/clusters", "cluster list")
op("POST", PRJ + "/clusters", "cluster create / cluster clone")
op("GET", CLU, "cluster get / cluster group list")
op("PUT", CLU, "cluster update / cluster scale / cluster group add / cluster group remove", "Description, support, "
   "scale out/in/up/down (capacity-checked), step scaling, adding and removing service groups.")
op("DELETE", CLU, "cluster delete", "`--discard-snapshots` maps to `retainsnapshotbackups=false`.")
op("GET", CLU + "/stats", "internal: bucket memory and scale-in checks", "No `cluster stats` command.", status=DONE)
op("POST", CLU + "/activationState", "cluster power on")
op("DELETE", CLU + "/activationState", "cluster power off")
op("PUT", CLU + "/deletionProtection", "cluster protect")
op("PUT", CLU + "/bucketStorageMigration", "cluster migrate-buckets")
# Free tier (clusters + buckets; the App Service free tier is in the 2.0.0 report)
op("POST", PRJ + "/clusters/freeTier", "cluster create", "Uses `--free-tier`.", stories="CAP-041")
op("GET", FT, "cluster get", stories="CAP-041")
op("PUT", FT, "cluster update", "The API accepts only name and description.", stories="CAP-041")
op("DELETE", FT, "cluster delete", stories="CAP-041")
op("POST", FT + "/activationState", "cluster power on", "Free tier: no body; also turns on linked App Services.",
   stories="CAP-019")
op("DELETE", FT + "/activationState", "cluster power off", stories="CAP-019")
op("GET", FB, "bucket list", stories="CAP-041")
op("POST", FB, "bucket create", stories="CAP-041")
op("GET", FB + "/{bucketId}", "bucket get", stories="CAP-041")
op("PUT", FB + "/{bucketId}", "bucket update", stories="CAP-041")
op("DELETE", FB + "/{bucketId}", "bucket delete", stories="CAP-041")
# On/Off schedule
op("GET", CLU + "/onOffSchedule", "cluster schedule show", "Also read by plan, import and the power note.")
op("POST", CLU + "/onOffSchedule", "cluster schedule set / cluster schedule apply")
op("PUT", CLU + "/onOffSchedule", "cluster schedule set / cluster schedule apply")
op("DELETE", CLU + "/onOffSchedule", "cluster schedule delete")
op("DELETE", CLU + "/onOffSchedule/activationState", "cluster schedule pause")
op("POST", CLU + "/onOffSchedule/activationState", "cluster schedule resume")
# Allowed CIDRs
op("GET", CLU + "/allowedcidrs", "cidr list")
op("POST", CLU + "/allowedcidrs", "cidr create", "No PUT exists, so a changed entry is replaced (delete + create).")
op("GET", CLU + "/allowedcidrs/{allowedCidrId}", "—", "Wired in the API client but unused: `cidr list` returns the "
   "same fields.", status=NONE)
op("DELETE", CLU + "/allowedcidrs/{allowedCidrId}", "cidr delete")
# Buckets, scopes, collections
op("GET", CLU + "/buckets", "bucket list")
op("POST", CLU + "/buckets", "bucket create")
op("GET", BKT, "bucket get")
op("PUT", BKT, "bucket update", "Immutable fields (type, storage backend, vbuckets, conflict resolution, eviction) are "
   "blocked.")
op("DELETE", BKT, "bucket delete")
op("PUT", BKT + "/flush", "bucket flush", "Not exposed in 1.0.0 (CAP-024); 1.5.0 adds it behind a typed confirmation.")
op("GET", BKT + "/scopes", "scope list", "Also read by `plan`, `import` and `collection delete`.")
op("POST", BKT + "/scopes", "scope create", "Also `collection create` for a new scope, and `apply`.")
op("GET", BKT + "/scopes/{scopeName}", "scope delete", "Lists the collections the confirmation shows.")
op("DELETE", BKT + "/scopes/{scopeName}", "scope delete", "Also `apply --prune`. Refused for `_default`/`_system` and "
   "on a protected cluster.")
op("GET", BKT + "/scopes/{scopeName}/collections", "collection list", "Also read by `plan`.")
op("POST", BKT + "/scopes/{scopeName}/collections", "collection create", "Also `apply`; `maxTTL` sent only when set.")
op("GET", BKT + "/scopes/{scopeName}/collections/{collectionName}", "collection update",
   "Reads the ETag sent as `If-Match` on the update.")
op("PUT", BKT + "/scopes/{scopeName}/collections/{collectionName}", "collection update", "`maxTTL` only; BLOCKED below "
   "Couchbase Server 7.6.0.")
op("DELETE", BKT + "/scopes/{scopeName}/collections/{collectionName}", "collection delete", "Also `apply --prune`.")
# Database credentials
op("GET", CLU + "/users", "credential list", "Also read by `import`, the `bucket delete` guard and `plan`.")
op("POST", CLU + "/users", "credential create", "Basic access only in 1.0.0; a generated password is saved locally.")
op("GET", CLU + "/users/{userId}", "credential get", "Never returns the password.")
op("PUT", CLU + "/users/{userId}", "credential update", "Access changes and password rotation (`--rotate-password`).")
op("DELETE", CLU + "/users/{userId}", "credential delete", "Also `apply --prune`; the local password file is kept.")
# Database roles
op("GET", CLU + "/privileges", "db-role privileges")
op("GET", CLU + "/roles", "db-role list")
op("POST", CLU + "/roles", "db-role create")
op("GET", CLU + "/roles/{roleId}", "db-role get")
op("PUT", CLU + "/roles/{roleId}", "db-role update")
op("DELETE", CLU + "/roles/{roleId}", "db-role delete")
# Sample buckets
op("POST", CLU + "/sampleBuckets", "sample-bucket load")
op("GET", CLU + "/sampleBuckets", "sample-bucket list")
op("GET", CLU + "/sampleBuckets/{bucketId}", "sample-bucket get")
op("DELETE", CLU + "/sampleBuckets/{bucketId}", "sample-bucket delete")
# Query indexes
op("POST", CLU + "/queryService/indexes", "index create / index drop / index build", "One `CREATE`, `DROP` or `BUILD INDEX` statement per call.")
op("GET", CLU + "/queryService/indexes", "index list")
op("GET", CLU + "/queryService/indexes/{indexName}", "index get")
op("GET", CLU + "/queryService/indexBuildStatus/{indexName}", "index status")
# Eventing
EV = CLU + "/eventingFunctions"
op("GET", EV, "eventing list")
op("POST", EV, "eventing create")
op("GET", EV + "/{functionName}", "eventing get")
op("PUT", EV + "/{functionName}", "eventing update")
op("DELETE", EV + "/{functionName}", "eventing delete")
op("GET", EV + "/{functionName}/code", "eventing code get")
op("PUT", EV + "/{functionName}/code", "eventing code set")
op("PUT", EV + "/{functionName}/activationState", "eventing state")
op("GET", EV + "/{functionName}/logs", "eventing logs")
# Data API
DA = CLU + "/dataAPI"
op("GET", DA, "data-api show")
op("PUT", DA, "data-api update")
op("POST", DA + "/privateEndpointCommand", "data-api endpoint-command")
op("GET", DA + "/privateEndpoints", "data-api endpoint list")
op("POST", DA + "/privateEndpoints/{endpointId}/associate", "data-api endpoint accept")
op("POST", DA + "/privateEndpoints/{endpointId}/unassociate", "data-api endpoint reject")
# Replications (XDCR)
RP = CLU + "/replications"
op("GET", RP, "replication list")
op("GET", PRJ + "/replications", "replication list", "Project-wide listing (`--project`).")
op("POST", RP, "replication create")
op("GET", RP + "/{replicationId}", "replication get")
op("PUT", RP + "/{replicationId}", "replication update")
op("DELETE", RP + "/{replicationId}", "replication delete")
op("DELETE", RP + "/{replicationId}/activationStatus", "replication pause")
op("POST", RP + "/{replicationId}/activationStatus", "replication resume")
op("GET", RP + "/jobs/{jobId}", "replication job")
# Backups & restore (bucket)
op("POST", BKT + "/backups", "bucket backup create")
op("GET", CLU + "/backups", "bucket backup list")
op("GET", CLU + "/backups/{backupId}", "bucket backup get")
op("DELETE", CLU + "/backups/{backupId}", "bucket backup delete", "Deletes the whole backup cycle.")
op("POST", CLU + "/backups/{backupId}/restore", "bucket backup restore", "Same or another cluster; partial restores.")
op("POST", BKT + "/backups/{backupId}/export", "bucket backup export", "Packages a backup cycle as a zip.")
op("GET", BKT + "/backups/{backupId}/exports/{exportId}", "bucket backup export", "Polled for the download URL.")
BS = BKT + "/backup"
op("GET", BS + "/schedules", "bucket backup schedule show", "Also read by plan, sync and drift.")
op("POST", BS + "/schedules", "bucket backup schedule set")
op("PUT", BS + "/schedules", "bucket backup schedule set")
op("DELETE", BS + "/schedules", "bucket backup schedule delete")
op("GET", BS + "/cycles", "bucket backup cycle list")
op("GET", BS + "/cycles/{cycleId}", "bucket backup cycle get")
# Cloud snapshot backups (cluster backups)
CS = CLU + "/cloudsnapshotbackups"
op("POST", CS, "cluster backup create")
op("GET", CS, "cluster backup list")
op("GET", PRJ + "/cloudsnapshotbackups", "cluster backup list", "Project-wide listing (no cluster name).")
op("GET", CS + "/restores", "cluster backup restores")
op("GET", CS + "/regions", "cluster backup regions / cluster backup schedule options", "Regions a copy can go to.")
op("PUT", CS + "/{backupId}", "cluster backup retain", "Changes retention.")
op("DELETE", CS + "/{backupId}", "cluster backup delete")
op("POST", CS + "/{backupId}/restore", "cluster backup restore")
op("POST", PRJ + "/cloudsnapshotbackups/{backupId}/clone", "cluster backup clone", "Creates a new cluster from the "
   "backup.")
op("GET", CLU + "/cloudsnapshotbackupschedule", "cluster backup schedule show", "Also read by plan, sync and drift.")
op("PUT", CLU + "/cloudsnapshotbackupschedule", "cluster backup schedule set")
op("DELETE", CLU + "/cloudsnapshotbackupschedule", "cluster backup schedule delete")
op("GET", CLU + "/cloudsnapshotbackupschedule/options", "cluster backup schedule options / cluster backup schedule set",
   "Permitted intervals and retention for the support plan; read before every set.")
# Network peers
NP = CLU + "/networkPeers"
op("POST", NP, "peer create")
op("GET", NP, "peer list")
op("GET", NP + "/{peerId}", "peer get")
op("DELETE", NP + "/{peerId}", "peer delete")
op("POST", NP + "/networkPeerCommand", "peer azure-command")
# Private endpoint service
PE = CLU + "/privateEndpointService"
op("GET", PE, "private-endpoint show")
op("POST", PE, "private-endpoint enable")
op("PUT", PE, "private-endpoint update")
op("DELETE", PE, "private-endpoint disable")
op("GET", PE + "/endpoints", "private-endpoint list")
op("POST", PE + "/endpointCommand", "private-endpoint command")
op("POST", PE + "/endpoints/{endpointId}/associate", "private-endpoint accept")
op("POST", PE + "/endpoints/{endpointId}/unassociate", "private-endpoint reject")
# Certificates
op("GET", CLU + "/certificates", "cluster certificate", "Useful for TLS client setup.")
# Audit logs
op("GET", CLU + "/auditLog", "audit-log get")
op("PUT", CLU + "/auditLog", "audit-log update")
op("GET", CLU + "/auditLogEvents", "audit-log events")
op("POST", CLU + "/auditLogExports", "audit-log export create")
op("GET", CLU + "/auditLogExports", "audit-log export list")
op("GET", CLU + "/auditLogExports/{auditLogExportId}", "audit-log export get")
# CMEK
AZ = "Azure, project level (`--project`)."
op("GET", ORG + "/cloudAccounts", "cmek accounts")
op("GET", ORG + "/cmekAzureApplication", "cmek azure-app")
op("GET", PRJ + "/cmekAzureApplication", "cmek azure-app", "Project level (`--project`).")
op("POST", ORG + "/cmek", "cmek create")
op("POST", PRJ + "/cmek", "cmek create", AZ)
op("GET", ORG + "/cmek", "cmek list")
op("GET", PRJ + "/cmek", "cmek list", AZ)
op("GET", ORG + "/cmek/{cmekId}", "cmek get")
op("GET", PRJ + "/cmek/{cmekId}", "cmek get", AZ)
op("GET", ORG + "/cmek/{cmekId}/history", "cmek history")
op("PUT", ORG + "/cmek/{cmekId}", "cmek rotate")
op("PUT", PRJ + "/cmek/{cmekId}", "cmek rotate", AZ)
op("DELETE", ORG + "/cmek/{cmekId}", "cmek delete")
op("DELETE", PRJ + "/cmek/{cmekId}", "cmek delete", AZ)
op("PUT", ORG + "/cmek/providers", "cmek enable-provider")
op("PUT", PRJ + "/cmek/providers", "cmek enable-provider", AZ)
op("POST", CLU + "/cmek/{cmekId}/associate", "cmek associate")
op("POST", CLU + "/cmek/{cmekId}/unassociate", "cmek unassociate")
# Alert integrations
AI = PRJ + "/alertIntegrations"
op("POST", AI, "alert create")
op("GET", AI, "alert list")
op("POST", AI + "/channels", "alert channels")
op("GET", AI + "/{alertIntegrationId}", "alert get")
op("PUT", AI + "/{alertIntegrationId}", "alert update")
op("DELETE", AI + "/{alertIntegrationId}", "alert delete")
op("POST", PRJ + "/alertIntegrationTest", "alert test")
# Events
op("GET", ORG + "/events", "event list")
op("GET", PRJ + "/events", "event list", "Project level (`--project`).")
op("GET", ORG + "/events/{eventId}", "event get")
op("GET", PRJ + "/events/{eventId}", "event get", "Project level (`--project`).")
# Organization users
op("POST", ORG + "/users", "user create")
op("GET", ORG + "/users", "user list")
op("GET", ORG + "/users/{userId}", "user get")
op("PATCH", ORG + "/users/{userId}", "user update")
op("DELETE", ORG + "/users/{userId}", "user delete")
# API keys
op("POST", ORG + "/apikeys", "apikey create")
op("GET", ORG + "/apikeys", "apikey list")
op("GET", ORG + "/apikeys/{ApiKeyId}", "apikey get")
op("DELETE", ORG + "/apikeys/{ApiKeyId}", "apikey delete")
op("POST", ORG + "/apikeys/{ApiKeyId}/rotate", "apikey rotate")
# Billing
op("POST", ORG + "/billing", "billing get", "Categorized.")
op("POST", CLU + "/billing", "billing get", "Itemized for one cluster (`--cluster`).")
op("GET", ORG + "/billing/prePaidCredits", "billing prepaid")
op("GET", ORG + "/billing/payAsYouGo", "billing payg")
op("POST", ORG + "/billing/download", "billing download")
op("POST", CLU + "/billing/download", "billing download", "Itemized for one cluster (`--cluster`).")

# Operational Insights clusters (a separate analytics cluster type, not the operational database)
OI = PRJ + "/operationalInsightsClusters"
OIC = OI + "/{analyticsClusterId}"
op("POST", OI, "insights create")
op("GET", OI, "insights list")
op("GET", ORG + "/operationalInsightsClusters", "insights list", "Organization level.")
op("GET", OIC, "insights get")
op("PUT", OIC, "insights update")
op("DELETE", OIC, "insights delete")
op("POST", OIC + "/activationState", "insights power on")
op("DELETE", OIC + "/activationState", "insights power off")
op("GET", OIC + "/onOffSchedule", "insights schedule show")
op("POST", OIC + "/onOffSchedule", "insights schedule set")
op("PUT", OIC + "/onOffSchedule", "insights schedule set")
op("DELETE", OIC + "/onOffSchedule", "insights schedule delete")
op("GET", OIC + "/allowedcidrs", "insights cidr list")
op("POST", OIC + "/allowedcidrs", "insights cidr create")
op("GET", OIC + "/allowedcidrs/{allowedCidrId}", "insights cidr get")
op("DELETE", OIC + "/allowedcidrs/{allowedCidrId}", "insights cidr delete")
OB = OIC + "/cloudSnapshotBackups"
op("POST", OB, "insights backup create")
op("GET", OB, "insights backup list")
op("PUT", OB + "/{backupId}", "insights backup retain")
op("DELETE", OB + "/{backupId}", "insights backup delete")
op("POST", OB + "/{backupId}/restore", "insights backup restore")
op("GET", OB + "/restores", "insights backup restores")
op("GET", OIC + "/cloudSnapshotBackupSchedule", "insights backup schedule show")
op("PUT", OIC + "/cloudSnapshotBackupSchedule", "insights backup schedule set")
op("DELETE", OIC + "/cloudSnapshotBackupSchedule", "insights backup schedule delete")
OP = OIC + "/privateEndpointService"
op("GET", OP, "insights private-endpoint show")
op("POST", OP, "insights private-endpoint enable")
op("DELETE", OP, "insights private-endpoint disable")
op("POST", OP + "/endpointCommand", "insights private-endpoint command")
op("GET", OP + "/endpoints", "insights private-endpoint list")
op("POST", OP + "/endpoints/{endpointId}/associate", "insights private-endpoint accept")
op("POST", OP + "/endpoints/{endpointId}/unassociate", "insights private-endpoint reject")

AREAS = [  # (spec tag, label, in 1.0.0 scope)
    ("Organizations", "Organizations", True), ("Projects", "Projects", True), ("Clusters", "Clusters", True),
    ("Free Tier", "Free tier (clusters & buckets)", True), ("On/Off Schedule", "On/Off schedule (hibernation)", True),
    ("Allowed CIDRs (Cluster)", "Allowed CIDRs (cluster)", True),
    ("Buckets, Scopes, & Collections", "Buckets, scopes & collections", True),
    ("Database Credentials", "Database credentials", True), ("Database Roles", "Database roles (custom)", False),
    ("Sample Bucket", "Sample buckets", False), ("Query Indexes", "Query indexes", False),
    ("Eventing Functions", "Eventing functions", False), ("Data API", "Data API", False),
    ("Replications", "Replications (XDCR)", False), ("Backups & Restore (Bucket)", "Backups & restore (bucket)", True),
    ("Backup Schedule (Bucket)", "Backup schedule (bucket)", True),
    ("Cloud Snapshot Backups & Restore", "Cloud snapshot backups & restore (cluster)", True),
    ("Cloud Snapshot Backups Schedule", "Cloud snapshot backup schedule (cluster)", True),
    ("Network Peers", "Network peers", False), ("Private Endpoint Service", "Private endpoint service", False),
    ("Certificates", "Certificates", False), ("Audit Logs", "Audit logs", False),
    ("CMEK", "CMEK (customer-managed keys)", False), ("Alert Integration", "Alert integrations", False),
    ("Events", "Events", False), ("Users", "Organization users", False), ("Api Keys", "API keys", False),
    ("Billing", "Billing", False),
    ("Operational Insights Clusters", "Operational Insights clusters", False),
    ("Operational Insights On/Off Schedule", "Operational Insights on/off schedule", False),
    ("Allowed CIDRs (Operational Insights Cluster)", "Allowed CIDRs (Operational Insights)", False),
    ("Operational Insights Cloud Snapshot Backups & Restore", "Operational Insights snapshot backups & restore", False),
    ("Operational Insights Cloud Snapshot Backups Schedule", "Operational Insights snapshot backup schedule", False),
    ("Operational Insights Private Endpoint Service", "Operational Insights private endpoints", False),
]

GAPS = [
    "**`GET …/allowedcidrs/{id}`** is wired in `capellactl/api/endpoints.py` but never called. Keep it for symmetry "
    "or drop it from `INVENTORY`.",
]

# ======================================================================== App Services (release 2.0.0)
AS = CLU + "/appservices/{appServiceId}"
FTA = CLU + "/appservices/freeTier"
EP = AS + "/appEndpoints/{appEndpointName}"
KS = AS + "/appEndpoints/{appEndpointKeyspace}"
AS_OPS: dict[tuple[str, str], tuple[str, str]] = {}


def aop(method: str, path: str, command: str, note: str = "") -> None:
    AS_OPS[(method, path)] = (command, note)


aop("GET", ORG + "/appservices", "app-service list", "Lists App Services across the organization.")
aop("POST", CLU + "/appservices", "app-service create", "Needs a provisioned cluster (1.0.0 `cluster create`). Async (202).")
aop("GET", AS, "app-service get")
aop("PUT", AS, "app-service update", "Scales nodes and compute.")
aop("DELETE", AS, "app-service delete")
aop("POST", AS + "/activationState", "app-service power on",
    "1.0.0 `turn_cluster_on` already sends `turnOnLinkedAppService` (default false).")
aop("DELETE", AS + "/activationState", "app-service power off")
aop("GET", AS + "/certificates", "app-service certificate")
aop("GET", AS + "/metadataIsolation", "app-service metadata-isolation show")
aop("PUT", AS + "/metadataIsolation", "app-service metadata-isolation enable", "One-way opt back in.")
aop("POST", AS + "/adminUsers", "app-service admin-user create")
aop("GET", AS + "/adminUsers", "app-service admin-user list")
aop("GET", AS + "/adminUsers/{userId}", "app-service admin-user get")
aop("PUT", AS + "/adminUsers/{userId}", "app-service admin-user update")
aop("DELETE", AS + "/adminUsers/{userId}", "app-service admin-user delete")
aop("GET", EP + "/adminUsers", "app-endpoint admin-user list")
aop("POST", FTA, "app-service create", "Free tier (`--free-tier`), mirroring 1.0.0 `cluster create --free-tier`.")
aop("GET", FTA + "/{appServiceId}", "app-service get", "Free tier.")
aop("PUT", FTA + "/{appServiceId}", "app-service update", "Free tier.")
aop("DELETE", FTA + "/{appServiceId}", "app-service delete", "Free tier.")
aop("GET", AS + "/allowedcidrs", "app-service cidr list", "Same model as 1.0.0 `cidr` (no PUT, so a change is delete + create).")
aop("POST", AS + "/allowedcidrs", "app-service cidr create")
aop("DELETE", AS + "/allowedcidrs/{allowedCidrId}", "app-service cidr delete")
AE = AS + "/appEndpoints"
aop("GET", AE, "app-endpoint list")
aop("POST", AE, "app-endpoint create")
aop("GET", EP, "app-endpoint get")
aop("PUT", EP, "app-endpoint update")
aop("DELETE", EP, "app-endpoint delete")
aop("GET", EP + "/collections", "app-endpoint collections")
aop("POST", EP + "/activationStatus", "app-endpoint resume", "Brings the endpoint online.")
aop("DELETE", EP + "/activationStatus", "app-endpoint pause", "Takes the endpoint offline.")
aop("GET", EP + "/cors", "app-endpoint cors show")
aop("PUT", EP + "/cors", "app-endpoint cors set")
aop("GET", KS + "/accessControlFunction", "app-endpoint access-function show")
aop("PUT", KS + "/accessControlFunction", "app-endpoint access-function set")
aop("DELETE", KS + "/accessControlFunction", "app-endpoint access-function delete")
aop("GET", KS + "/importFilter", "app-endpoint import-filter show")
aop("PUT", KS + "/importFilter", "app-endpoint import-filter set")
aop("DELETE", KS + "/importFilter", "app-endpoint import-filter delete")
aop("POST", EP + "/oidcProviders", "app-endpoint oidc create")
aop("GET", EP + "/oidcProviders", "app-endpoint oidc list")
aop("GET", EP + "/oidcProviders/{OIDCProviderId}", "app-endpoint oidc get")
aop("PUT", EP + "/oidcProviders/{OIDCProviderId}", "app-endpoint oidc update")
aop("DELETE", EP + "/oidcProviders/{OIDCProviderId}", "app-endpoint oidc delete")
aop("PUT", EP + "/oidcProviders/defaultProvider", "app-endpoint oidc set-default")
aop("GET", EP + "/resync", "app-endpoint resync status")
aop("POST", EP + "/resync", "app-endpoint resync start")
aop("DELETE", EP + "/resync", "app-endpoint resync stop")
aop("GET", AS + "/auditLog", "app-service audit-log show")
aop("PUT", AS + "/auditLog", "app-service audit-log set", "Enables or disables audit logging.")
aop("GET", EP + "/auditLog", "app-endpoint audit-log show")
aop("PUT", EP + "/auditLog", "app-endpoint audit-log set")
aop("GET", EP + "/auditLogEvents", "app-endpoint audit-log events")
aop("PUT", AS + "/auditLogStreaming", "app-service audit-stream configure")
aop("PATCH", AS + "/auditLogStreaming", "app-service audit-stream resume", "Starts or resumes streaming.")
aop("GET", AS + "/auditLogStreaming", "app-service audit-stream show")
aop("POST", AS + "/auditLogExports", "app-service audit-log export create")
aop("GET", AS + "/auditLogExports", "app-service audit-log export list")
aop("GET", AS + "/auditLogExports/{auditLogExportId}", "app-service audit-log export get")
aop("POST", AS + "/logStreaming", "app-service log-stream configure")
aop("GET", AS + "/logStreaming", "app-service log-stream show")
aop("DELETE", AS + "/logStreaming", "app-service log-stream disable")
aop("POST", AS + "/logStreaming/activationState", "app-service log-stream resume")
aop("DELETE", AS + "/logStreaming/activationState", "app-service log-stream pause")
aop("GET", EP + "/logStreaming", "app-endpoint log-stream show")
aop("PUT", EP + "/logStreaming", "app-endpoint log-stream set")
ASPE = AS + "/privateEndpointService"
aop("POST", ASPE, "app-service private-endpoint enable")
aop("GET", ASPE, "app-service private-endpoint show")
aop("DELETE", ASPE, "app-service private-endpoint disable")
aop("POST", ASPE + "/privateEndpointCommand", "app-service private-endpoint command")
aop("GET", ASPE + "/endpoints", "app-service private-endpoint list")
aop("POST", ASPE + "/endpoints/{endpointId}", "app-service private-endpoint accept")
aop("DELETE", ASPE + "/endpoints/{endpointId}", "app-service private-endpoint reject")

AS_AREAS = [("App Services", "App Services"), ("App Services (free tier)", "Free Tier"),
            ("Allowed CIDRs (App Services)", "Allowed CIDRs (App Services)"), ("App Endpoints", "App Endpoints"),
            ("App Services audit logging", "App Services Audit Logging"),
            ("App Services log streaming", "App Services Log Streaming"),
            ("App Services private endpoints", "App Services Private Endpoints")]


# ======================================================================== helpers
def is_app_services(tag: str, path: str) -> bool:
    return "App Service" in tag or tag == "App Endpoints" or "/appservices" in path


def is_ai(tag: str) -> bool:
    return tag.startswith(("AI ", "MCP ")) or "Model" in tag


def anchor(tag: str) -> str:
    s = tag.replace(" & ", " and ").replace("&", "and").replace(",", "").replace("/", "-")
    return REF + re.sub(r"\s+", "-", s)


def short(path: str) -> str:
    return (path.replace(ORG, "{org}").replace("/projects/{projectId}", "/projects/{p}")
            .replace("/clusters/{clusterId}", "/clusters/{c}").replace("/freeTier/{clusterId}", "/freeTier/{c}")
            .replace("/buckets/{bucketId}", "/buckets/{b}")
            .replace("/appservices/{appServiceId}", "/appservices/{a}")
            .replace("/appEndpoints/{appEndpointName}", "/appEndpoints/{e}")
            .replace("/appEndpoints/{appEndpointKeyspace}", "/appEndpoints/{keyspace}"))


def pct(a: int, b: int) -> str:
    return f"{round(100 * a / b)}%" if b else "—"


def load_stories() -> dict[str, dict[str, str]]:
    """{id: {status, title, file, release}} from each story's header table."""
    out = {}
    for d in STORY_DIRS:
        for f in sorted(d.glob("CAP-*.md")):
            lines = f.read_text(encoding="utf-8").splitlines()
            m = re.match(r"^# (CAP-\d+) — (.+)$", lines[0])
            row = next((ln for ln in lines[1:8] if ln.startswith("|") and not ln.startswith("|---")
                        and "Status" not in ln), None)
            if not m or row is None:
                sys.exit(f"{f.name}: cannot read the story header")
            out[m.group(1)] = {"status": [c.strip() for c in row.strip("|").split("|")][-1], "title": m.group(2),
                               "file": f.name, "release": d.name.removeprefix("release-")}
    return out


def ver(release: str) -> tuple[int, ...]:
    return tuple(int(x) for x in release.split("."))


def in_release(stories: tuple[str, ...], known: dict[str, dict[str, str]], release: str) -> tuple[str, ...]:
    """The stories delivered by `release` or an earlier one (a gap counts in every release)."""
    return tuple(s for s in stories if s == NO_STORY or ver(known[s]["release"]) <= ver(release))


def release_of(stories: tuple[str, ...], known: dict[str, dict[str, str]]) -> str:
    """The release that completes these stories: the latest of theirs ("" when none has a story)."""
    rels = [known[s]["release"] for s in stories if s != NO_STORY]
    return max(rels, key=ver) if rels else ""


def story_link(s: str, known: dict[str, dict[str, str]], here: str) -> str:
    """Link to a story file from the report of release `here`."""
    k = known[s]
    return k["file"] if k["release"] == here else f"../release-{k['release']}/{k['file']}"


def status_of(stories: tuple[str, ...], known: dict[str, dict[str, str]], release: str) -> str:
    stories = in_release(stories, known, release)
    if not stories:
        return LATER
    done = [s != NO_STORY and known[s]["status"] in ("Implemented", "Descoped") for s in stories]
    return DONE if all(done) else PART if any(done) else TODO


def open_stories(stories: tuple[str, ...], known: dict[str, dict[str, str]], release: str) -> list[str]:
    return [s for s in in_release(stories, known, release)
            if s == NO_STORY or known[s]["status"] not in ("Implemented", "Descoped")]


def collect_ops(snapshot: dict[str, Any], known: dict[str, dict[str, str]]) -> tuple[list[dict[str, Any]],
                                                                                    collections.Counter[str]]:
    """Every operational-database operation with its commands and stories, after checking the maps."""
    excl: collections.Counter[str] = collections.Counter()
    for stories, _ in COMMANDS.values():
        for s in stories:
            if s != NO_STORY and s not in known:
                sys.exit(f"command dictionary names unknown story {s}")
    for _, stories, _ in WORKFLOW:
        for s in (x.strip() for x in stories.split(",")):
            if s not in known:
                sys.exit(f"workflow command names unknown story {s}")
    ops = []
    for o in snapshot["operations"]:
        tag, m, p = o["tag"], o["method"], o["path"]
        if is_app_services(tag, p):
            excl["as"] += 1
            continue
        if is_ai(tag):
            excl["ai"] += 1
            continue
        spec = OPS.get((m, p))
        if spec is None:
            sys.exit(f"unmapped operation {m} {p} ({tag}): add it to OPS in {Path(__file__).name}")
        names = [] if spec["commands"].startswith(("internal", "—")) else spec["commands"].split(" / ")
        for n in names:
            if n not in COMMANDS:
                sys.exit(f"{m} {p}: command '{n}' is not in the command dictionary")
        for s in spec["stories"] + spec["requires"]:
            if s != NO_STORY and s not in known:
                sys.exit(f"{m} {p}: unknown story {s}")
        base = spec["stories"] or tuple(dict.fromkeys(s for n in names for s in COMMANDS[n][0]))
        ops.append({"tag": tag, "method": m, "path": p, "summary": o["summary"], "names": names,
                    "stories": base + spec["requires"], "fixed": spec["status"],
                    **{k: spec[k] for k in ("commands", "note", "left", "requires", "partial_use")}})
    extra = set(OPS) - {(o["method"], o["path"]) for o in ops}
    if extra:
        sys.exit(f"OPS maps operations that are not in the spec snapshot: {sorted(extra)}")
    if {o["tag"] for o in ops} != {a[0] for a in AREAS}:
        sys.exit(f"spec tags changed: {sorted({o['tag'] for o in ops} ^ {a[0] for a in AREAS})}")
    return ops, excl


def op_status(o: dict[str, Any], known: dict[str, dict[str, str]], release: str) -> str:
    if o["fixed"]:
        return str(o["fixed"])
    st = status_of(o["stories"], known, release)
    return PART if st == TODO and o["partial_use"] else st


def breakdown(snapshot: dict[str, Any], known: dict[str, dict[str, str]]) -> list[str]:
    """The same table in every report: where each operation in the spec is tracked."""
    ops, excl = collect_ops(snapshot, known)
    rows: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])  # group: [operations, done]
    for o in ops:
        if o["fixed"] == NONE:
            group = "none"
        else:
            group = release_of(o["stories"], known) or (REL10 if o["fixed"] else "")
        rows[group][0] += 1
        rows[group][1] += op_status(o, known, group or REL15) == DONE
    r10, r15, r20 = ("../release-1.0.0/API-COVERAGE.md", "../release-1.5.0/API-COVERAGE.md",
                     "../release-2.0.0/API-COVERAGE-APP-SERVICES.md")
    # (group, operations, done or None when the group is never built, tracked in)
    table: list[tuple[str, int, int | None, str]] = [
        ("Operational database, release 1.0.0", *rows[REL10], f"[1.0.0 report]({r10})"),
        ("Operational database, not needed (another operation gives the same data)", rows["none"][0], None,
         f"[1.0.0 report]({r10})"),
        ("Operational database, release 1.5.0", *rows[REL15], f"[1.5.0 report]({r15})")]
    if rows[""][0]:
        table.append(("Operational database, no release yet", *rows[""], "—"))
    table += [("App Services / App Endpoints, release 2.0.0", excl["as"], 0, f"[2.0.0 report]({r20})"),
              ("AI (AI Data Plane, AI Workflows, Models, AI Agent Memory, MCP servers and tools)", excl["ai"], None,
               "Not planned")]
    total = sum(n for _, n, _, _ in table)
    if total != len(snapshot["operations"]):
        sys.exit(f"operation breakdown adds up to {total}, the spec has {len(snapshot['operations'])}")
    out = ["**Where the spec's operations go**\n", "| Group | Operations | ✅ Done | Tracked in |", "|---|---|---|---|"]
    out += [f"| {g} | {n} | {'—' if d is None else d} | {where} |" for g, n, d, where in table]
    out += [f"| **Total in the spec** | **{total}** | **{sum(d or 0 for _, _, d, _ in table)}** | |", ""]
    return out


# ======================================================================== operational-database report
def build_db(snapshot: dict[str, Any], known: dict[str, dict[str, str]], table: list[str]) -> str:  # noqa: C901 - one report, top to bottom
    all_ops = snapshot["operations"]
    ops, excl = collect_ops(snapshot, known)
    for o in ops:
        o["status"] = op_status(o, known, REL10)
    cmd_status = {n: status_of(st, known, REL10) for n, (st, _) in COMMANDS.items()}

    cmd_ops: dict[str, list[str]] = collections.defaultdict(list)
    for o in ops:
        for n in o["names"]:
            cmd_ops[n].append(f"{o['method']} {short(o['path'])}")

    def count(rows: list[dict[str, Any]]) -> list[int]:
        c = collections.Counter(r["status"] for r in rows)
        return [c.get(s, 0) for s in ORDER]

    ops10 = [o for o in ops if o["status"] != LATER]
    cmds10 = {n: s for n, s in cmd_status.items() if s != LATER}
    oc, o10 = count(ops), count(ops10)
    cc = collections.Counter(cmd_status.values())
    c10 = collections.Counter(cmds10.values())
    wf = [(n, status_of(tuple(x.strip() for x in st.split(",")), known, REL10), st, note) for n, st, note in WORKFLOW]
    wc = collections.Counter(s for _, s, _, _ in wf)
    by: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for o in ops:
        by[o["tag"]].append(o)

    out: list[str] = []
    w = out.append
    w("# Management API coverage — operational database\n")
    w(f"> Generated by `scripts/update-api-coverage.py` from the Capella Management API {snapshot['apiVersion']} spec "
      f"([source]({snapshot['source']}), snapshot of {snapshot['retrieved']} in "
      "[docs/api](../api/management-api-v4.0-operations.json)), the command dictionary in that script and the "
      "**Status** of each story. Every in-scope operation in the spec appears exactly once. Don't edit by hand: "
      "change a story's status and run `make coverage`. CI fails when this file is stale. Story progress: "
      "[README.md](README.md).\n")
    w("## Scope\n")
    w(f"The spec has **{len(all_ops)} operations**. Release 1.0.0 is about the operational database, so this report "
      f"covers the **{len(ops)} operational-database operations**. Two groups are left out:\n")
    w(f"- **{excl['as']} App Services / App Endpoints operations**, including the 4 free-tier App Service operations. "
      "They are tracked in [release 2.0.0: App Services API coverage](../release-2.0.0/API-COVERAGE-APP-SERVICES.md).")
    w(f"- **{excl['ai']} AI operations** (AI Data Plane, AI Workflows, Models, AI Agent Memory, MCP servers and tools). Not planned for now.\n")
    out += table
    w("**Status legend**\n")
    w("| Status | Meaning |\n|---|---|")
    w(f"| {DONE} | capellactl calls this operation, from a command, from `plan`/`apply`, or internally, and every story "
      "it depends on is Implemented. |")
    w(f"| {PART} | Some of it is built (some of its stories are Implemented, or a read during `import`); the row says "
      "what is left. |")
    w(f"| {TODO} | Planned for 1.0.0 in a story that is not Implemented yet. Its command may exist as a stub that "
      "prints \"not available in this build\". |")
    w(f"| {NONE} | Not needed: another operation already provides the same data. |")
    w(f"| {LATER} | Outside the 1.0.0 scope (see [00-architecture.md §14](00-architecture.md)). Planned for "
      "[release 1.5.0](../release-1.5.0/API-COVERAGE.md), which tracks their stories. |")
    w("")
    w("## Summary\n")
    w("### API operations\n")
    w("| | Operations | ✅ Done | 🟡 Partial | ⬜ Not built | ➖ Not needed | ⏭️ Not in 1.0 | Coverage (done / total) |")
    w("|---|---|---|---|---|---|---|---|")
    w(f"| **Planned for 1.0.0** | **{len(ops10)}** | {o10[0]} | {o10[1]} | {o10[2]} | {o10[3]} | — | "
      f"**{pct(o10[0], len(ops10) - o10[3])}** (done / needed) |")
    w(f"| All operational-database operations | {len(ops)} | {oc[0]} | {oc[1]} | {oc[2]} | {oc[3]} | {oc[4]} | "
      f"{pct(oc[0], len(ops))} |")
    w("")
    w("### Commands\n")
    w("| | Commands | ✅ Done | 🟡 Partial | ⬜ Not built (stub) | ⏭️ Not in 1.0 | Coverage (done / total) |")
    w("|---|---|---|---|---|---|---|")
    w(f"| **Resource commands planned for 1.0.0** | **{len(cmds10)}** | {c10[DONE]} | {c10[PART]} | {c10[TODO]} | — | "
      f"**{pct(c10[DONE], len(cmds10))}** |")
    w(f"| Workflow commands (`plan`, `apply`, …) | {len(wf)} | {wc[DONE]} | {wc[PART]} | {wc[TODO]} | — | "
      f"{pct(wc[DONE], len(wf))} |")
    w(f"| All resource commands, including later releases | {len(COMMANDS)} | {cc[DONE]} | {cc[PART]} | {cc[TODO]} | "
      f"{cc[LATER]} | {pct(cc[DONE], len(COMMANDS))} |")
    w("")
    w("*Each verb counts as one command (for example `cluster schedule pause`). Each command maps to one or more API "
      "operations. For example, `bucket create` calls both the provisioned and the free-tier create.*\n")
    w("### By area\n")
    w("| Area | 1.0.0 scope | Ops | ✅ | 🟡 | ⬜ | ➖ | ⏭️ |")
    w("|---|---|---|---|---|---|---|---|")
    for tag, label, scoped in AREAS:
        c = count(by[tag])
        w(f"| [{label}]({anchor(tag)}) | {'Yes' if scoped else 'No'} | {len(by[tag])} | "
          + " | ".join(str(x or "") for x in c) + " |")
    w(f"| **Total** | | **{len(ops)}** | **{oc[0]}** | **{oc[1]}** | **{oc[2]}** | **{oc[3]}** | **{oc[4]}** |")
    w("")

    w("## What is left for 1.0.0\n")
    left = [o for o in ops10 if o["status"] in (PART, TODO)]
    per_story: dict[str, dict[str, list[str]]] = collections.OrderedDict()
    for o in sorted(left, key=lambda x: open_stories(x["stories"], known, REL10)):
        for s in open_stories(o["stories"], known, REL10):
            entry = per_story.setdefault(s, {"ops": [], "cmds": []})
            entry["ops"].append(f"`{o['method']} {short(o['path'])}`")
            entry["cmds"] += [f"`{n}`" for n in o["names"] if s in COMMANDS[n][0] or s in o["requires"]]
    for n, st, stories, _ in wf:
        if st != DONE:
            for s in open_stories(tuple(x.strip() for x in stories.split(",")), known, REL10):
                per_story.setdefault(s, {"ops": [], "cmds": []})["cmds"].append(f"`{n}`")
    w(f"{len(left)} operations are partial or not built, across {len(per_story)} stories:\n")
    w("| Story | Status | Operations | Commands |")
    w("|---|---|---|---|")
    for s in sorted(per_story, key=lambda x: (x == NO_STORY, x)):
        e = per_story[s]
        story = ("**No story yet** (gap)" if s == NO_STORY
                 else f"[{s}]({known[s]['file']}) {known[s]['title']}")
        status = "—" if s == NO_STORY else known[s]["status"]
        w(f"| {story} | {status} | {', '.join(dict.fromkeys(e['ops'])) or '— (uses the operations above)'} | "
          f"{', '.join(dict.fromkeys(e['cmds']))} |")
    w("")
    w("### Gaps found\n")
    for i, g in enumerate(GAPS, 1):
        w(f"{i}. {g}")
    w("")

    w("## Command dictionary\n")
    w("Every resource command: built, stubbed, or planned for a later release, with the API operations it calls. A "
      "command's status "
      "comes from its stories.\n")
    w("### Planned for 1.0.0\n")
    w("| Command | Status | Stories | API operations | What's left |")
    w("|---|---|---|---|---|")
    for n, st in cmds10.items():
        stories, lft = COMMANDS[n]
        ops_txt = "<br>".join(f"`{x}`" for x in dict.fromkeys(cmd_ops.get(n, [])))
        w(f"| `capellactl {n}` | {st} | {', '.join(stories)} | {ops_txt} | {'' if st == DONE else lft} |")
    w("")
    w("### Workflow commands (not one-to-one with an API operation)\n")
    w("| Command | Status | Stories | Notes |")
    w("|---|---|---|---|")
    for n, st, stories, note in wf:
        w(f"| `capellactl {n}` | {st} | {stories} | {note} |")
    w("")
    w("### Commands outside 1.0.0\n")
    w(f"<details><summary>{cc[LATER]} commands planned for a later release</summary>\n")
    w("| Command | Release | Stories | API operations |")
    w("|---|---|---|---|")
    for n, st in cmd_status.items():
        if st == LATER:
            stories = COMMANDS[n][0]
            links = ", ".join(f"[{s}]({story_link(s, known, REL10)})" for s in stories if s != NO_STORY)
            w(f"| `capellactl {n}` | {release_of(stories, known) or '—'} | {links or '—'} | "
              f"{'<br>'.join(f'`{x}`' for x in dict.fromkeys(cmd_ops.get(n, [])))} |")
    w("\n</details>\n")

    w("## Operation-by-operation table\n")
    w("Paths are abbreviated: `{org}` = `/v4/organizations/{organizationId}`, `{p}` = projectId, `{c}` = clusterId, "
      "`{b}` = bucketId.\n")
    for tag, label, scoped in AREAS:
        rows = by[tag]
        c = count(rows)
        sumtxt = ", ".join(f"{c[i]} {ORDER[i].split(' ', 1)[0]}" for i in range(len(ORDER)) if c[i])
        w(f"### {label} — {len(rows)} ops ({sumtxt})\n")
        w(f"[API reference]({anchor(tag)}){' · out of 1.0.0 scope' if not scoped else ''}\n")
        w("| Operation | Method | Path | capellactl command | Status | Notes / what's left |")
        w("|---|---|---|---|---|---|")
        for o in rows:
            cmdtxt = o["commands"] if not o["names"] else " / ".join(f"`{x}`" for x in o["names"])
            notes = " ".join(x for x in (o["note"], "" if o["status"] == DONE else o["left"]) if x)
            w(f"| {o['summary']} | `{o['method']}` | `{short(o['path'])}` | {cmdtxt} | {o['status']} | {notes} |")
        w("")
    return "\n".join(out)


# ======================================================================== release 1.5.0 report
def build_15(snapshot: dict[str, Any], known: dict[str, dict[str, str]], table: list[str]) -> str:  # noqa: C901 - one report, top to bottom
    ops, excl = collect_ops(snapshot, known)
    for o in ops:
        o["status"] = op_status(o, known, REL15)
    unplanned = [f"{o['method']} {o['path']}" for o in ops if o["status"] == LATER]
    if unplanned:
        sys.exit(f"operations planned for no release (give their commands a story): {unplanned}")

    def planned_15(stories: tuple[str, ...]) -> bool:
        return release_of(stories, known) == REL15

    ops15 = [o for o in ops if planned_15(o["stories"])]
    earlier = [o for o in ops if not planned_15(o["stories"])]
    cmds15 = {n: status_of(st, known, REL15) for n, (st, _) in COMMANDS.items() if planned_15(st)}
    cmd_ops: dict[str, list[str]] = collections.defaultdict(list)
    for o in ops15:
        for n in o["names"]:
            cmd_ops[n].append(f"{o['method']} {short(o['path'])}")
    order = [DONE, PART, TODO]

    def count(rows: list[dict[str, Any]]) -> list[int]:
        c = collections.Counter(r["status"] for r in rows)
        return [c.get(s, 0) for s in order]

    c15, cc = count(ops15), collections.Counter(cmds15.values())
    done_before = sum(o["status"] == DONE for o in earlier)
    not_needed = sum(o["status"] == NONE for o in ops)
    by: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for o in ops15:
        by[o["tag"]].append(o)
    before_by = collections.Counter(o["tag"] for o in earlier)

    out: list[str] = []
    w = out.append
    w("# Management API coverage — release 1.5.0\n")
    w(f"> Generated by `scripts/update-api-coverage.py` from the Capella Management API {snapshot['apiVersion']} spec "
      f"([source]({snapshot['source']}), snapshot of {snapshot['retrieved']} in "
      "[docs/api](../api/management-api-v4.0-operations.json)), the command dictionary in that script and the "
      "**Status** of each story. Don't edit by hand: change a story's status and run `make coverage`. CI fails when "
      "this file is stale. Story progress: [README.md](README.md).\n")
    w("## Scope\n")
    w(f"The spec has **{len(snapshot['operations'])} operations**, of which **{len(ops)} are operational-database "
      f"operations**. [Release 1.0.0](../release-1.0.0/API-COVERAGE.md) covers {len(earlier)} of them. **Release 1.5.0 "
      f"plans the other {len(ops15)}**, so that after 1.5.0 capellactl calls every operational-database operation it "
      "needs. Two groups stay out:\n")
    w(f"- **{excl['as']} App Services / App Endpoints operations**: release 2.0.0 "
      "([API coverage](../release-2.0.0/API-COVERAGE-APP-SERVICES.md)).")
    w(f"- **{excl['ai']} AI operations** (AI Data Plane, AI Workflows, Models, AI Agent Memory, MCP servers and tools). "
      "Not planned for now.\n")
    out += table
    w("**Status legend**\n")
    w("| Status | Meaning |\n|---|---|")
    w(f"| {DONE} | capellactl calls this operation and every story it depends on is Implemented. |")
    w(f"| {PART} | Some of its stories are Implemented; the row says what is left. |")
    w(f"| {TODO} | Planned for 1.5.0 in a story that is not Implemented yet. |")
    w("")
    w("## Summary\n")
    w("| | Count | ✅ Done | 🟡 Partial | ⬜ Not built | Coverage (done / total) |")
    w("|---|---|---|---|---|---|")
    w(f"| **API operations planned for 1.5.0** | **{len(ops15)}** | {c15[0]} | {c15[1]} | {c15[2]} | "
      f"**{pct(c15[0], len(ops15))}** |")
    w(f"| **Resource commands planned for 1.5.0** | **{len(cmds15)}** | {cc[DONE]} | {cc[PART]} | {cc[TODO]} | "
      f"**{pct(cc[DONE], len(cmds15))}** |")
    w(f"| Operational database after 1.5.0 (1.0.0 + 1.5.0) | {len(ops) - not_needed} | {done_before + c15[0]} | "
      f"{c15[1]} | {c15[2] + len(earlier) - not_needed - done_before} | "
      f"{pct(done_before + c15[0], len(ops) - not_needed)} |")
    w("")
    w(f"*The last row leaves out the {not_needed} operation{'s' if not_needed != 1 else ''} marked ➖ Not needed in the "
      "1.0.0 report. Each verb counts as one command; a command can call more than one operation.*\n")
    w("### By area\n")
    w("| Area | In 1.0.0 | 1.5.0 ops | ✅ | 🟡 | ⬜ | Stories |")
    w("|---|---|---|---|---|---|---|")
    for tag, label, _ in AREAS:
        rows = by.get(tag)
        if not rows:
            continue
        c = count(rows)
        stories = sorted({s for o in rows for s in o["stories"] if s != NO_STORY and known[s]["release"] == REL15})
        w(f"| [{label}]({anchor(tag)}) | {before_by[tag] or ''} | {len(rows)} | "
          + " | ".join(str(x or "") for x in c) + " | "
          + ", ".join(f"[{s}]({story_link(s, known, REL15)})" for s in stories) + " |")
    w(f"| **Total** | | **{len(ops15)}** | **{c15[0]}** | **{c15[1]}** | **{c15[2]}** | |")
    w("")

    w("## What is left for 1.5.0\n")
    left = [o for o in ops15 if o["status"] in (PART, TODO)]
    per_story: dict[str, dict[str, list[str]]] = collections.OrderedDict()
    for o in left:
        for s in open_stories(o["stories"], known, REL15):
            entry = per_story.setdefault(s, {"ops": [], "cmds": []})
            entry["ops"].append(f"`{o['method']} {short(o['path'])}`")
            entry["cmds"] += [f"`{n}`" for n in o["names"] if s in COMMANDS[n][0] or s in o["requires"]]
    w(f"{len(left)} operations are partial or not built, across {len(per_story)} stories:\n")
    w("| Story | Status | Operations | Commands |")
    w("|---|---|---|---|")
    for s in sorted(per_story, key=lambda x: (x == NO_STORY, x)):
        e = per_story[s]
        story = ("**No story yet** (gap)" if s == NO_STORY
                 else f"[{s}]({story_link(s, known, REL15)}) {known[s]['title']}")
        status = "—" if s == NO_STORY else known[s]["status"]
        w(f"| {story} | {status} | {', '.join(dict.fromkeys(e['ops']))} | {', '.join(dict.fromkeys(e['cmds']))} |")
    w("")

    w("## Command dictionary\n")
    w("Every resource command planned for 1.5.0, with the API operations it calls. A command's status comes from its "
      "stories. Workflow commands (`plan`, `apply`, `sync`, `drift`, `destroy`) gain the new resources through the "
      "stories' acceptance criteria.\n")
    w("| Command | Status | Stories | API operations | What's left |")
    w("|---|---|---|---|---|")
    for n, st in cmds15.items():
        stories, lft = COMMANDS[n]
        links = ", ".join(f"[{s}]({story_link(s, known, REL15)})" for s in stories if s != NO_STORY)
        ops_txt = "<br>".join(f"`{x}`" for x in dict.fromkeys(cmd_ops.get(n, [])))
        w(f"| `capellactl {n}` | {st} | {links} | {ops_txt} | {'' if st == DONE else lft} |")
    w("")

    w("## Operation-by-operation table\n")
    w("Paths are abbreviated: `{org}` = `/v4/organizations/{organizationId}`, `{p}` = projectId, `{c}` = clusterId, "
      "`{b}` = bucketId.\n")
    for tag, label, _ in AREAS:
        rows = by.get(tag)
        if not rows:
            continue
        c = count(rows)
        sumtxt = ", ".join(f"{c[i]} {order[i].split(' ', 1)[0]}" for i in range(len(order)) if c[i])
        w(f"### {label} — {len(rows)} ops ({sumtxt})\n")
        extra = (f" · {before_by[tag]} more in [1.0.0](../release-1.0.0/API-COVERAGE.md)" if before_by[tag] else "")
        w(f"[API reference]({anchor(tag)}){extra}\n")
        w("| Operation | Method | Path | capellactl command | Status | Notes / what's left |")
        w("|---|---|---|---|---|---|")
        for o in rows:
            cmdtxt = " / ".join(f"`{x}`" for x in o["names"]) or o["commands"]
            notes = " ".join(x for x in (o["note"], "" if o["status"] == DONE else o["left"]) if x)
            w(f"| {o['summary']} | `{o['method']}` | `{short(o['path'])}` | {cmdtxt} | {o['status']} | {notes} |")
        w("")
    return "\n".join(out)


# ======================================================================== App Services report
def build_as(snapshot: dict[str, Any], table: list[str]) -> str:
    all_ops = snapshot["operations"]
    ops = []
    for o in all_ops:
        tag, m, p = o["tag"], o["method"], o["path"]
        if not is_app_services(tag, p):
            continue
        if (m, p) not in AS_OPS:
            sys.exit(f"unmapped App Services operation {m} {p} ({tag}): add it to AS_OPS in {Path(__file__).name}")
        ops.append((tag, m, p, o["summary"], *AS_OPS[(m, p)]))
    extra = set(AS_OPS) - {(m, p) for _, m, p, *_ in ops}
    if extra:
        sys.exit(f"AS_OPS maps operations that are not in the spec snapshot: {sorted(extra)}")
    by: dict[str, list[tuple[str, ...]]] = collections.defaultdict(list)
    for r in ops:
        by[r[0]].append(r)
    if set(by) != {t for _, t in AS_AREAS}:
        sys.exit(f"App Services tags changed: {sorted(set(by) ^ {t for _, t in AS_AREAS})}")
    cmds: dict[str, list[str]] = collections.OrderedDict()
    for _, m, p, _, c, _ in ops:
        cmds.setdefault(c, []).append(f"{m} {short(p)}")

    out: list[str] = []
    w = out.append
    w("# Management API coverage — App Services (release 2.0.0)\n")
    w(f"> Generated by `scripts/update-api-coverage.py` from the Capella Management API {snapshot['apiVersion']} spec "
      f"([source]({snapshot['source']}), snapshot of {snapshot['retrieved']}). Every App Services operation in the spec "
      "appears exactly once. Operational-database coverage is in "
      "[release-1.0.0/API-COVERAGE.md](../release-1.0.0/API-COVERAGE.md) and "
      "[release-1.5.0/API-COVERAGE.md](../release-1.5.0/API-COVERAGE.md). Don't edit by hand.\n")
    w("## Scope\n")
    w(f"The spec has **{len(all_ops)} operations**. This document tracks the **{len(ops)} App Services and App Endpoints "
      "operations**, including the 4 free-tier App Service operations that the spec tags *Free Tier*. Releases 1.0.0 "
      "and 1.5.0 cover the operational database. The AI operations are not planned for now.\n")
    out += table
    w("No stories are written for 2.0.0 yet. Every row is ⏭️ **Not started**, and every command name is a proposal "
      "that follows the 1.0.0 conventions: noun-verb, declarative through `plan`/`apply`, and idempotent.\n")
    w("## Summary\n")
    w("| | Count | ✅ Done | 🟡 Partial | ⬜ Not built | ⏭️ Not started | Coverage |")
    w("|---|---|---|---|---|---|---|")
    w(f"| **API operations** | **{len(ops)}** | 0 | 0 | 0 | {len(ops)} | 0% |")
    w(f"| **Proposed commands** | **{len(cmds)}** | 0 | 0 | 0 | {len(cmds)} | 0% |")
    w("")
    w("### By area\n")
    w("| Area | Operations | Proposed commands |")
    w("|---|---|---|")
    for label, tag in AS_AREAS:
        w(f"| [{label}]({anchor(tag)}) | {len(by[tag])} | {len({r[4] for r in by[tag]})} |")
    w(f"| **Total** | **{len(ops)}** | **{len(cmds)}** |")
    w("")
    w("*A command can serve more than one operation, for example `app-service create` with and without "
      "`--free-tier`, so the per-area command counts add up to more than the distinct total.*\n")
    w("## Dependencies on 1.0.0\n")
    w("- An App Service is created **under a provisioned cluster** (`POST …/clusters/{c}/appservices`), so it builds on "
      "the 1.0.0 cluster, bucket, scope and collection reconcilers. App Endpoints bind to a bucket's scopes and "
      "collections, which needs [CAP-025](../release-1.0.0/CAP-025-ensure-scopes-collections.md).")
    w("- `POST …/clusters/{c}/activationState` (1.0.0 `cluster power on`, "
      "[CAP-019](../release-1.0.0/CAP-019-power-cluster-off-on.md)) already accepts `turnOnLinkedAppService`. In 1.0.0 it "
      "is always `false`; 2.0.0 should expose it.")
    w("- Deleting a cluster that has a linked App Service needs an ordering rule in the 1.0.0 dependency graph "
      "([00-architecture.md](../release-1.0.0/00-architecture.md) §4.2): delete the App Service first.")
    w("- The patterns for allowed CIDRs, audit-log export, private endpoints and power on/off mirror the "
      "cluster-level 1.0.0 work, so their reconcilers and tests can be reused.\n")
    w("## Command dictionary (proposed)\n")
    w("| Command | Status | API operations |")
    w("|---|---|---|")
    for c, lst in cmds.items():
        w(f"| `capellactl {c}` | ⏭️ Not started | {'<br>'.join(f'`{x}`' for x in lst)} |")
    w("")
    w("## Operation-by-operation table\n")
    w("Paths are abbreviated: `{org}` = `/v4/organizations/{organizationId}`, `{p}` = projectId, `{c}` = clusterId, "
      "`{a}` = appServiceId, `{e}` = appEndpointName.\n")
    for label, tag in AS_AREAS:
        rows = by[tag]
        w(f"### {label} — {len(rows)} ops\n")
        w(f"[API reference]({anchor(tag)})\n")
        w("| Operation | Method | Path | Proposed command | Status | Notes |")
        w("|---|---|---|---|---|---|")
        for _, m, p, s, c, n in rows:
            w(f"| {s} | `{m}` | `{short(p)}` | `{c}` | ⏭️ Not started | {n} |")
        w("")
    return "\n".join(out)


# ======================================================================== main
def refresh(url: str) -> None:
    import datetime

    import yaml

    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - fixed https documentation URL
        spec = yaml.safe_load(r.read())
    ops = [{"tag": (o.get("tags") or ["?"])[0], "method": m.upper(), "path": p, "summary": o.get("summary", "")}
           for p, item in spec["paths"].items() for m, o in item.items()
           if m in ("get", "post", "put", "patch", "delete")]
    snap = {"source": url, "apiVersion": spec["info"]["version"],
            "retrieved": datetime.date.today().isoformat(), "operations": ops}
    SNAPSHOT.write_text(json.dumps(snap, indent=1) + "\n", encoding="utf-8")
    print(f"{SNAPSHOT.relative_to(ROOT)}: {len(ops)} operations")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 when a report is out of date")
    ap.add_argument("--refresh-spec", nargs="?", const=SPEC_URL, metavar="URL", help="re-download the spec first")
    args = ap.parse_args()
    if args.refresh_spec:
        refresh(args.refresh_spec)
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    known = load_stories()
    table = breakdown(snapshot, known)
    reports = {OUT_DB: build_db(snapshot, known, table) + "\n", OUT_15: build_15(snapshot, known, table) + "\n",
               OUT_AS: build_as(snapshot, table) + "\n"}
    stale = [p for p, text in reports.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    if args.check:
        if stale:
            names = ", ".join(str(p.relative_to(ROOT)) for p in stale)
            sys.exit(f"{names} out of date: run 'python3 scripts/update-api-coverage.py' (or 'make coverage') "
                     "and commit the result")
        print("API coverage reports are up to date")
        return
    for p, text in reports.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    print(f"API coverage reports written: {', '.join(str(p.relative_to(ROOT)) for p in reports)}")


if __name__ == "__main__":
    main()
