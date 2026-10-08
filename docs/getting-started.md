# Getting started with capellactl

A step-by-step walkthrough from installation to day-2 operations. For copy-paste commands see the [cheatsheet](release-1.0.0/cheatsheet.md); for any command, `capellactl help` or `--help`.

## Step by step

These steps use only what is built now, and every step is a `capellactl` command. capellactl writes and maintains `capella.yaml` for you; you never edit it by hand. It stays in the folder as the record of your environment (handy for reviews and version control).

**1. Prerequisites**

- Python 3.10–3.13 and `git`.
- A Capella organization and an API key: Capella UI → **Organization settings → API Keys**. Give it **Organization Owner**, or **Project Creator** plus **Project Owner** on the project you will use, and add your machine's public IP to the key's allowed IPs. Copy the **API Key Token** when the key is created: Capella shows it only once, and the API Key ID will not work.

**2. Install from the repository**

```bash
git clone <this repository> capellactl && cd capellactl
python3.12 -m venv .venv
.venv/bin/pip install -e .
source .venv/bin/activate          # puts capellactl on your PATH
capellactl --version               # capellactl 1.0.0.dev0 (Management API v4.0)
```

**3. Connect and discover**

Run this in the folder where you want `capella.yaml`:

```bash
capellactl configure
```
```
Paste the API Key Token from Capella (Organization settings → API Keys). It is shown once when the key is created; the API Key ID will not work.
Capella API Key Token (input hidden):
profile 'default' saved (org Nova Corp) in ~/.config/capellactl/profiles.yaml
API Key Token stored in the OS keychain
Discover your projects and clusters and write capella.yaml now? [Y/n]: y
Imported 2 projects, 1 cluster, 1 bucket, 0 scopes, 0 collections, 0 credentials, 0 allowed CIDRs, 0 hibernation schedules into capella.yaml
Next: capellactl plan    (reports no changes for what was imported)
```

- The token is checked against Capella and stored in your OS keychain, never in a file.
- An existing `capella.yaml` is never rewritten without asking. If it belongs to another organization, or declares a project that organization does not have, `configure` says so and offers to back it up and re-import it (default: keep it).
- One `capella.yaml` holds **all your projects**, each with its clusters. `capellactl import --project NAME` limits discovery to some of them.
- Projects and clusters are recorded with their `id:`, so a rename in the Capella UI shows in `plan` as a rename (`capellactl sync` keeps the new name) instead of a new project. To copy the file to another organization, delete the `id:` lines first.
- Nothing in Capella is changed: discovery only reads. Passwords are never exported (Capella never returns them).
- Run `capellactl import` again at any time: it adds projects that are not in the file yet and leaves the others alone (`capellactl sync` refreshes those, step 11).

**Starting from scratch instead?** `capellactl init` asks a few questions (project, cluster name, provider and region, size preset, support plan, deletion protection, office-hours hibernation, allowed IP ranges, a first bucket and app credential) and writes a commented, validated `capella.yaml`; then `capellactl plan` shows what `apply` will create. It only reads from Capella (to list your organizations and projects), never writes the API key or any password (a credential gets `password: ${ORDERS_APP_PASSWORD}`), asks before overwriting an existing file (keeping a `.bak`), and offers to `import` an existing project instead. Size presets live in `capellactl/config/presets.yaml`. For scripts:

```bash
capellactl init --non-interactive --project nova-dev --cluster nova-dev-01 --provider aws --region us-east-1 \
  --preset small --hibernation office-hours --timezone US/Pacific --cidr 203.0.113.10/32
capellactl init --dry-run            # print the YAML instead of writing it
```

**4. Projects: list, create, delete**

```bash
capellactl project list                                   # every project; IN FILE shows which are in capella.yaml
capellactl project create non-prod --description "QA"     # creates it in Capella and adds it to capella.yaml
capellactl project delete non-prod                        # asks you to type the name; removes it from capella.yaml too
```
```
ID     NAME      DESCRIPTION   CREATED               IN FILE
p-1    demo      Demo          2026-01-01T00:00:00Z  yes
p-2    non-prod  QA            2026-10-05T18:02:11Z  yes
```

`project create` refuses a name that already exists in Capella (add those with `capellactl import --project NAME`). `project delete` refuses a project that still has clusters unless you add `--cascade`, which deletes them first (refused while a cluster has deletion protection; snapshot backups are kept unless `--discard-snapshots`). Then deploy the first cluster of the new project with step 6 (`--project non-prod`).
- In CI, or without a keychain: export `CAPELLA_API_KEY` and `CAPELLA_ORG_ID`, then run `capellactl import --project NAME`.

**5. Check: plan reports no changes**

```bash
capellactl plan
```
```
Project nova-dev · organization 6af0…

  = project nova-dev
  = cluster nova-dev-01
  = bucket nova-dev-01/orders

Plan: 0 to add, 0 to change, 0 to delete, 0 blocked.
```

`=` matches, `+` will be created, `~` will change, `!` blocked, `…` deferred (waits for its parent, for example a cluster that is not healthy yet). `plan` never changes anything.

**6. Deploy a new cluster**

See what you can deploy first:

```bash
capellactl cluster options
```
```
Free tier          available
  1 node · data, index, query, search · no cost · one per organization
  aws    us-east-2, eu-west-1, ap-southeast-1
  gcp    us-central1, europe-west1, asia-east1
  azure  eastus, swedencentral, koreacentral
  deploy: capellactl cluster create NAME --free-tier [--provider aws --region us-east-2]

Provisioned        available
  providers        aws, gcp, azure
  sizes            dev (1 × 4 vCPU/16 GB, single node, aws), small (3 × 4 vCPU/16 GB), medium …, large …, custom
  regions          any region of the provider; in use by your clusters: aws us-east-1
```

The free tier is offered only while your organization has not used it. Capella's API does not publish a list of regions or sizes per organization, so for provisioned clusters capellactl suggests the regions you already use; one Capella does not offer is rejected with Capella's own message.

**Free tier, to try things out** (one per organization, 1 node, no cost):

```bash
capellactl cluster create try-01 --free-tier                      # asks provider and a free-tier region
capellactl --auto-approve cluster create try-01 --free-tier --provider aws --region us-east-2
```

**Provisioned cluster:**

```bash
capellactl cluster create nova-dev-02
```
```
Cloud provider (aws, gcp, azure) [aws]:
Size (dev, small, medium, large, custom) [small]:
Region [us-east-1]:
Network CIDR (must not overlap other clusters) [10.0.0.0/24]:
Support plan (basic, developer pro, enterprise) [developer pro]:
New cluster nova-dev-02: aws us-east-1, 3 × 4 vCPU/16 GB, network 10.0.0.0/24, support developer pro

  + cluster nova-dev-02  aws us-east-1 · multi-AZ · 3 × 4 vCPU/16 GB · data,index,query · developer pro

Add nova-dev-02 to capella.yaml and deploy it now? [y/N]: y
→ creating cluster nova-dev-02 …
  cluster nova-dev-02: deploying (0s) ...................
  cluster nova-dev-02: healthy (9m40s)
  done cluster nova-dev-02 in 9m41s
connectionString (nova-dev-02): couchbases://cb.xxxx.cloud.couchbase.com
Apply complete in 9m41s.
```

While a cluster deploys, scales or is deleted a dot is printed every 30 seconds, so a long wait never looks stuck; the total time is shown when it finishes.

With several projects in capella.yaml, you are first asked which project (or pass `--project NAME`). If the free tier is still available you are then asked `Cluster type (free, provisioned)`. Press Enter to accept a default. The suggested network never overlaps your other clusters. Anything invalid is explained and asked again; nothing is written or deployed until you confirm. For scripts, pass everything as options:

```bash
capellactl --auto-approve cluster create nova-qa-01 --project non-prod --provider gcp --size medium --support-plan enterprise
```

Sizes: `dev` (1 node, AWS), `small` (3 × 4 vCPU/16 GB), `medium` (3 × 8/32), `large` (5 × 16/64), or `custom`. `capellactl cluster create --help` lists every option. A new cluster usually takes several minutes; apply waits until it is healthy (`--no-wait` returns at once).

**7. Change a cluster**

```bash
capellactl cluster scale nova-dev-01 --nodes 4                      # scale out
capellactl cluster update nova-dev-01 --support-plan enterprise     # support plan, description
capellactl cluster update nova-dev-01 --cpu 8 --ram 32              # bigger nodes
capellactl cluster update nova-dev-01                               # asks what to change
```

Each command shows the plan (for example `~ cluster nova-dev-01   scale out  numOfNodes: 3 → 4`), asks once, records the change in `capella.yaml` and applies it. `--no-apply` only records it; `capellactl apply` deploys it later. If two projects have a cluster with the same name, add `--project NAME`. Even a description or support-plan change starts a cluster job in Capella (listed as "scale" in the Capella UI, nodes unchanged), so the plan notes it and the command waits until the cluster is healthy again.

**8. Add, change and delete buckets, scopes and collections**

```bash
capellactl bucket create nova-dev-01 events --memory 1024 --storage-backend magma --durability majority
capellactl bucket update nova-dev-01 events --memory 2048          # memory, replicas, durability, TTL, flush
capellactl bucket list nova-dev-01
capellactl bucket delete nova-dev-01 events                        # asks you to type the bucket name
capellactl scope create nova-dev-01 orders billing
capellactl collection create nova-dev-01 orders billing invoices --max-ttl 2592000   # -1 never expire, 0 bucket TTL
capellactl collection update nova-dev-01 orders billing invoices --max-ttl -1
capellactl collection list nova-dev-01 orders billing
capellactl scope delete nova-dev-01 orders billing                 # asks you to type the scope name
```
```
  + bucket nova-dev-01/events  couchbase · magma · 1024 MB · 1 replica · durability majority
```

Like the cluster commands, `create` and `update` show the plan, ask once, record the bucket in `capella.yaml` and apply it (`--no-apply` only records it). `create` for a bucket that already exists in Capella adds it to the file without re-creating it. A bucket that does not fit the cluster's free memory, or asks for more replicas than the cluster has data nodes for, is refused before anything changes; so is a change to `type`, `storageBackend`, `vbuckets`, `bucketConflictResolution` or `evictionPolicy`. `delete` shows the item count, memory used and the credentials that lose access, removes the bucket from `capella.yaml`, and is refused while the cluster has deletion protection. Removing a bucket from the file deletes nothing; `capellactl apply --prune` does. On a free-tier cluster only `--memory` can be set (Capella chooses the rest).

Scopes and collections work the same way. `collection create` also adds its scope when it is new, and `_default` can hold your own collections (`collection create nova-dev-01 orders _default legacy`); the `_default` and `_system` scopes and the `_default` collection are never created, changed or deleted. `maxTTL` is compared only when you set it, and changing it needs Couchbase Server 7.6.0 or later (older clusters are refused before anything changes). Scopes and collections are created before the credentials that use them. `delete` lists the collections whose documents go and the credentials that lose access, asks you to type the name, removes it from `capella.yaml`, and is refused while the cluster has deletion protection. `plan` lists scopes and collections that are not in the file as unmanaged; only `apply --prune` deletes them.

**9. Give an application access**

```bash
export ORDERS_APP_PW='Orders-Passw0rd-2026!'     # 8+ chars, upper, lower, digit, special; none of < > ; . * & | £
capellactl credential create nova-dev-01 orders_app --privileges read+write --bucket orders --password-env ORDERS_APP_PW
capellactl credential list nova-dev-01
export ORDERS_APP_PW='Orders-Passw0rd-2026-v2!'
capellactl credential update nova-dev-01 orders_app --rotate-password     # sends the new $ORDERS_APP_PW
capellactl credential delete nova-dev-01 orders_app
```
```
  + credential nova-dev-01/orders_app  read+write · orders
```

Access is least privilege: `--bucket` (optionally `--scope` and `--collection`) or an explicit `--all-buckets`, with `read`, `write` or `read+write`. The password comes from the environment variable (`--password-env VAR`) or a file (`--password-file PATH`); capella.yaml records `${ORDERS_APP_PW}`, never the value. Without a password flag Capella generates one, written once to `.capellactl/credentials/<cluster>.<name>.json` (owner-only) and never printed. Passwords are never compared, so `apply` never changes a password behind a running application: rotate with `--rotate-password`, or all at once with `capellactl apply --rotate-passwords` (a configured `${VAR}` value is used, else a new one is generated and the previous local file kept as `.bak`). Weak passwords are refused offline. A credential with several grants is changed in `capella.yaml` and applied with `apply`. `delete` keeps the local password file and tells you where it is. An advanced credential (`userRoles`) with the same name is refused; those come in 1.1.

**10. Protect a cluster, control who can connect, delete a cluster**

```bash
capellactl cluster protect nova-dev-01 --on                          # deletion protection on
capellactl cidr create nova-dev-01 203.0.113.10/32 --comment "Office VPN"
capellactl cidr list nova-dev-01
capellactl cidr delete nova-dev-01 203.0.113.10/32
capellactl cluster protect nova-dev-01 --off                         # needed before deleting it
capellactl cluster delete nova-dev-01                                # asks you to type the cluster name
```
```
  - cluster nova-dev-01  aws us-east-1 · 3 nodes · 1 bucket
    buckets deleted with the cluster: orders
    snapshot backups are kept (--discard-snapshots deletes them)
Type the cluster name to confirm deletion: nova-dev-01
  cluster nova-dev-01: destroying (0s)
  cluster nova-dev-01: deleted (4m10s)
deleted cluster nova-dev-01 (snapshot backups retained)
```

`deletionProtection: true` in `capella.yaml` is applied right after a cluster is healthy and blocks every delete path (`cluster delete`, `bucket delete`, `scope delete`, `collection delete`, `project delete --cascade`, `apply --prune`, `destroy`) until you run `cluster protect NAME --off`. `cluster protect` also records the setting in `capella.yaml`, so the next `apply` keeps it. Allowed IP ranges have no update in Capella's API: a changed comment or expiry is applied as a replace (`±`). `plan` lists ranges that are in Capella but not in the file as unmanaged; only `apply --prune` deletes them. `cidr create` refuses `0.0.0.0/0` unless you pass `--allow-any-ip`. `cluster delete` waits until the cluster is gone, then removes it from `capella.yaml`.

**11. Bring in changes made outside capellactl**

If someone changes a cluster in the Capella UI, or creates a new one:

```bash
capellactl sync              # refreshes every project in capella.yaml and shows what changed
capellactl sync --project non-prod   # just one project
capellactl sync --dry-run    # just show the difference (exit 2 when out of date; good for CI)
```
```
--- capella.yaml (now)
+++ capella.yaml (from Capella)
-  description: Nova development cluster
+  description: changed in the Capella UI
capella.yaml updated from Capella (previous version kept as capella.yaml.bak).
```

Sync only reads from Capella. It keeps what Capella cannot return (password references such as `${APP_PASSWORD}`).

**12. Save money: power off, hibernation schedule, step scaling**

```bash
capellactl cluster power nova-dev-01 --off                      # stop compute now; data and settings stay
capellactl cluster power nova-dev-01 --on
capellactl cluster schedule set nova-dev-01 --timezone US/Pacific --weekdays 08:00-18:00 --weekend off
capellactl cluster schedule show nova-dev-01                    # weekly grid and the next on/off time
capellactl cluster schedule pause nova-dev-01 --power-on        # demo or incident: keep it on
capellactl cluster schedule resume nova-dev-01
capellactl cluster scale nova-dev-01 --step +1 --max 6          # one node more (exit 0 at the limit)
capellactl cluster scale nova-dev-01 --step -1 --min 3          # one node less, capacity-checked
```

The schedule and its paused state are recorded in `capella.yaml`; power is not (it is a moment, not a setting). While a cluster is off, `plan` blocks changes below it and says when the schedule turns it on again; `apply --power-on` turns it on first.

**13. Check for drift, tear down**

```bash
capellactl drift                         # changed, missing and unmanaged resources (read-only)
capellactl drift --detailed-exitcode     # CI: exit 2 when Capella and capella.yaml differ
capellactl apply --prune                 # also delete unmanaged buckets, scopes, credentials, CIDRs, schedules
capellactl destroy                       # delete everything capella.yaml declares, children first
```

`destroy` refuses while a cluster has deletion protection, asks you to type the project name, keeps snapshot backups unless `--discard-snapshots`, and keeps `capella.yaml` (only the ids of what it deleted are removed), so `capellactl apply` builds the environment again.

**14. What is refused, and why**

`plan`/`apply` stop before changing anything when a change is unsafe or impossible:

```
  ! cluster nova-dev-01  immutable: cloudProvider.region (requires a new cluster)
      cloudProvider.region:  "us-east-1" → "us-west-2"
      See: capellactl help idempotency
```

Fewer nodes, less RAM or a removed service group (scale-in) are checked first: the buckets must still fit in memory, every bucket's replicas need enough data nodes, `data` can never be removed, and removing the last nodes of another service or a whole group needs `--allow-service-removal` / `--allow-service-group-removal`:

```bash
capellactl cluster scale nova-dev-01 --nodes 3
```
```
  ~ cluster nova-dev-01   scale in
      serviceGroups[data,index,query].numOfNodes:  4 → 3
      checks: memory ok (1,024 / ~15,360 MB) · replicas ok (max 1, needs 2 data nodes)
```

Disks never shrink, and failed or degraded clusters are not changed. A turned-off cluster is powered on first (`capellactl cluster power NAME --on`, or `apply --power-on`). `capellactl help safety` explains each case.

**15. When something goes wrong**

- `configure` says "API Key Token rejected": the most common cause is the API key's **IP allowlist** (Capella UI → Organization settings → API Keys → your key) not including this machine's public IP (`curl -s https://checkip.amazonaws.com`). Also check that you copied the **API Key Token**, not the API Key ID. The message shows Capella's own hint and a `curl` command to test the key. To avoid pasting into the hidden prompt: `pbpaste | capellactl configure --api-key-stdin`.
- `plan` blocks a project with `probably renamed in Capella`: the project was renamed in the UI and the file has no `id:` for it. Run `capellactl sync` to adopt the new name (it also records the ids).
- `project NAME not found`: the `capella.yaml` in this folder is probably for another organization or project. Run `capellactl configure show` to see which file and organization are used; `capellactl import --force` rewrites the file for your organization (the old one is kept as `.bak`).
- Exit codes: `capellactl help exit-codes` (3 = config problem, 4 = blocked, 5 = timed out waiting).
- Details of every API call (secrets masked): `capellactl --log-level debug plan`.
- If apply stops halfway, fix the cause and run `capellactl apply` again; finished steps are not repeated.

## capella.yaml: written by capellactl

`capella.yaml` (`capella.yml` also works) describes all your projects and their clusters in one file. capellactl creates it and keeps it up to date; you do not need to edit it.

| How it changes | Command |
|---|---|
| Created from your Capella project | `capellactl configure` (offers it) or `capellactl import [--project NAME] [--cluster NAME]` |
| New project added | `capellactl project create NAME` |
| More existing projects added | `capellactl import` (adds the ones that are missing) |
| New cluster added and deployed | `capellactl cluster create NAME` |
| Cluster changed | `capellactl cluster update NAME …`, `capellactl cluster scale NAME --nodes N` |
| Refreshed after changes made in the Capella UI | `capellactl sync` |

Keep it in version control to review changes over time. `capellactl help config <field>` explains any field you see in it. Import only reads from Capella; passwords are never written (Capella does not return them) and existing passwords stay unchanged.
