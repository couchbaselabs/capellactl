# Getting started with capellactl

This guide takes you from nothing to a working Couchbase Capella environment, one command at a time. Each step
builds on the one before it:

| Section | You will | Changes Capella? | Time |
|---|---|---|---|
| [Connect to Capella](#connect-to-capella) | Save your API key, list what you have | No, read-only | 5 min |
| [Create your first cluster (free tier)](#create-your-first-cluster-free-tier) | Create a project, a free-tier cluster, a bucket and an app login | Yes, at no cost | 15 min |
| [Manage a provisioned cluster](#manage-a-provisioned-cluster) | Scale, change, protect, power off, bring in UI changes | Yes, a provisioned cluster is billed | 30 min+ |
| [Clean up](#clean-up) | Delete the provisioned cluster and the project | Yes | 10 min |
| [Build a whole environment in one go](#build-a-whole-environment-in-one-go) | Describe a whole environment, then create it with `apply` | Yes | 15 min |

Two things to know before you start:

- **Every command shows what it will do and asks before doing it.** Nothing changes until you answer `y`.
- **You never edit a file.** capellactl records what you create in `capella.yaml`, a plain description of your
  environment, so you can review it, keep it in Git, and rebuild from it later ([Build a whole environment in one go](#build-a-whole-environment-in-one-go)).

## Before you start

**A Capella API key.** In the Capella UI, go to **Organization settings → API Keys** and create a key:

- Role: **Organization Owner**, or **Project Creator** plus **Project Owner** on the project you will use.
- Allowed IPs: add this machine's public IP (`curl -s https://checkip.amazonaws.com` shows it).
- Copy the **API Key Token** when the key is created. Capella shows it only once, and the API Key ID will not work.

**capellactl installed.** Follow [Install](../README.md#install), then check it:

```bash
capellactl --version               # capellactl 1.0.0.devN+g… (Management API v4.0) before the first release
```

**A folder for your environment.** capellactl writes `capella.yaml` in the folder you run it from. Use a new one
(not the capellactl source folder, if you installed from source):

```bash
mkdir ~/capella-env && cd ~/capella-env
```

## Step by step

### Connect to Capella

Nothing in this part changes Capella.

**1. Connect**

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
- Answer `y` to discover: it only reads from Capella and writes what it finds to `capella.yaml`. Passwords are never
  exported (Capella never returns them).
- A new organization with no projects yet gets `This organization has no projects yet` instead; carry on with step 2;
  you will create your first project in step 3.

**2. Look around**

```bash
capellactl project list
capellactl cluster list                     # clusters of every project
```
```
S.NO  NAME      DESCRIPTION  CREATED               IN FILE  ID
1     web-shop  Online shop  2026-01-01T00:00:00Z  yes      4dbab271-8a31-4146-8af5-6ad09ec26d0a

S.NO  NAME           PROJECT   STATE    PROVIDER  REGION     NODES  PLAN           ID
1     web-shop-prod  web-shop  healthy  aws       us-east-1  3      developer pro  c77ec8a5-dd9d-440e-b526-5b628ec035ea
```

This is an organization that already has a project, `web-shop`. In a new organization both lists are empty; you will
fill them in the next section. Every list numbers its rows (`S.NO`) and
shows Capella's ID last; `IN FILE` shows what is recorded in `capella.yaml`. `capellactl help`, and `--help` on any
command, explain the rest.

### Create your first cluster (free tier)

Capella's free tier is a 1-node cluster at no cost. Each command below shows its plan and asks `[y/N]` before changing
anything.

> **Only one free-tier cluster per organization at a time.** Capella allows one free-tier cluster per organization
> (tenant), shared by everyone in it: while yours exists, no one else in your organization can create one. You delete
> it at the end of this section, before moving on.

**3. Create a project**

A project is a folder for clusters, usually one per application or environment (for example dev, test and prod).
Capella access rights can be given per project, so a project also decides who can see its clusters.

```bash
capellactl project create sandbox --description "Trying capellactl"
```
```
  + project sandbox  Trying capellactl

Plan: 1 to add, 0 to change, 0 to delete, 0 blocked.
Create project sandbox in Capella and write capella.yaml? [y/N]: y
project sandbox created (id p-1)
Next: capellactl cluster create NAME --project sandbox    (deploys the first cluster of this project)
```

`capellactl project list` now shows it. A name that already exists in Capella is refused; add an existing project to
the file with `capellactl import --project NAME`.

**4. See what you can deploy**

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
  sizes            dev (1 × 4 vCPU/16 GB, single node), small (3 × 4 vCPU/16 GB), medium (3 × 8 vCPU/32 GB), large (5 × 16 vCPU/64 GB), custom
```

If it says `not available: already used by …`, your organization already has its free cluster: use that cluster's
name in steps 6–10, or deploy a provisioned one (step 11, billed) and come back.

**5. Deploy a free-tier cluster**

```bash
capellactl cluster create try-01 --project sandbox
```
```
Cluster type (free, provisioned) [provisioned]: free
Cloud provider (aws, gcp, azure) [aws]: azure
Region (free-tier regions) (eastus, swedencentral, koreacentral) [eastus]:
Network CIDR (must not overlap other clusters) [10.0.0.0/24]:

  + cluster try-01  free tier · azure eastus · 1 node · data,index,query,search

Add try-01 to capella.yaml and deploy it now? [y/N]: y
→ creating cluster try-01 …
  cluster try-01: deploying (0s) ......
  cluster try-01: healthy (3m05s)
connectionString (try-01): couchbases://cb.xxxx.cloud.couchbase.com
Apply complete in 3m05s.
```

Press Enter to accept a default; anything invalid is explained and asked again. While a cluster deploys, a spinner
(`| / - \`) turns at the end of the line and a dot is added every 30 seconds, so a long wait never looks stuck. Now that it exists, look at it:

```bash
capellactl cluster list
capellactl cluster get try-01               # one cluster: state, size, connection string
```
```
NAME    STATE    PROVIDER  REGION  NODES  PLAN  ID
try-01  healthy  azure     eastus  1      free  5d760754-ae8f-448e-acb1-a66ed0e0cd41
  …
connectionString: couchbases://cb.xxxx.cloud.couchbase.com
```

**6. Add a bucket**

A bucket is where your documents (JSON data) live, much like a database. `--memory` is how much of the cluster's
memory, in MB, the bucket may use to keep data close at hand.

```bash
capellactl bucket create try-01 orders --memory 100
capellactl bucket list try-01
```
```
  + bucket try-01/orders  free tier · 100 MB
```

On the free tier only the memory can be set; on a provisioned cluster you can also choose replicas, durability,
storage backend and TTL (`capellactl bucket create --help`).

**7. Organise it: a scope and a collection**

Inside a bucket, documents are grouped in two levels: a **scope** holds **collections**, and a collection holds the
documents, much like a schema and its tables in a relational database. Applications often use one scope per
service or tenant, and one collection per document type. Every bucket starts with a `_default` scope and collection.

```bash
capellactl scope create try-01 orders inventory               # scope "inventory" in bucket "orders"
capellactl collection create try-01 orders inventory items    # collection "items" in that scope
capellactl collection list try-01 orders inventory            # the collections of the scope
```

**8. Let your machine connect to the cluster**

Capella accepts connections only from allowed IP ranges. A new cluster has none yet:

```bash
capellactl cidr list try-01
```
```
S.NO  CIDR  COMMENT  EXPIRES  STATUS  IN FILE
```

Allow this machine, then list again:

```bash
capellactl cidr create try-01 "$(curl -s https://checkip.amazonaws.com)/32" --comment "My laptop"
capellactl cidr list try-01
```
```
S.NO  CIDR             COMMENT    EXPIRES  STATUS  IN FILE
1     203.0.113.10/32  My laptop  never    active  yes
```

Your range shows your machine's public IP instead of the example `203.0.113.10`. `IN FILE: yes` shows that the range
was also recorded in `capella.yaml`. `0.0.0.0/0` (anyone) is refused unless you
add `--allow-any-ip`.

**9. Give an application a login**

Applications sign in to the cluster with a database credential. A new cluster has none yet:

```bash
capellactl credential list try-01
```
```
S.NO  NAME  TYPE  ACCESS  IN FILE
```

Create one that can read and write the `orders` bucket, then list again:

```bash
export ORDERS_APP_PASSWORD='Orders-Passw0rd-2026!'   # 8+ chars, upper, lower, digit, special; none of < > ; . * & | £
capellactl credential create try-01 orders_app --privileges read+write --bucket orders --password-env ORDERS_APP_PASSWORD
capellactl credential list try-01
```
```
  + credential try-01/orders_app  read+write · orders
...
S.NO  NAME        TYPE   ACCESS               IN FILE
1     orders_app  basic  read+write · orders  yes
```

The password is read from the environment variable and never written to a file or printed. Leave out
`--password-env` and Capella generates one, saved once to `.capellactl/credentials/` (only you can read it).

**10. See what was recorded**

```bash
cat capella.yaml
```
```yaml
projects:
  - name: sandbox
    description: Trying capellactl
    clusters:
      - id: c-2
        name: try-01
        tier: free
        cloudProvider: {type: azure, region: eastus, cidr: 10.0.0.0/24}
        allowedCidrs:
          - cidr: 203.0.113.10/32
            comment: My laptop
        buckets:
          - name: orders
            memoryAllocationInMb: 100
            scopes:
              - name: inventory
                collections:
                  - name: items
        databaseCredentials:
          - name: orders_app
            password: ${ORDERS_APP_PASSWORD}
            access:
              - privileges: [data_reader, data_writer]
                resources:
                  buckets:
                    - name: orders
```

Each command recorded its change, and the password is only a reference (`${ORDERS_APP_PASSWORD}`). This file is all
`capellactl apply` needs to build the same environment again ([Build a whole environment in one go](#build-a-whole-environment-in-one-go)).

Now compare it with Capella:

```bash
capellactl plan
```
```
Project sandbox · organization 6af0…

  = project sandbox
  = cluster try-01
  = allowed-cidr try-01/203.0.113.10/32
  = bucket try-01/orders
  = scope try-01/orders/inventory
  = collection try-01/orders/inventory/items
  = credential try-01/orders_app

Plan: 0 to add, 0 to change, 0 to delete, 0 blocked.
```

`plan` never changes anything. Here everything matches (`=`), because each command already applied what it recorded.
Later you will also see `+` (will be created), `~` (will change), `-` (will be deleted), `!` (blocked: unsafe or
impossible) and `…` (waits for something else, such as a cluster that is still deploying). If step 1 discovered
existing projects, they are listed too.

**Before you go on: delete the free-tier cluster**

The next section uses a provisioned cluster, so free the free-tier slot for others in your organization. Delete the
pieces one at a time, smallest first, to see what each delete does:

```bash
capellactl credential delete try-01 orders_app
capellactl cidr delete try-01 <203.0.113.10/32>      # your own range from step 8: copy it from cidr list
capellactl bucket delete try-01 orders               # asks you to type the bucket name
capellactl cluster delete try-01                     # asks you to type the cluster name; waits until it is gone
capellactl cluster options                           # Free tier: available again
```
```
  - cluster try-01  azure eastus · 1 node · 0 buckets
Type the cluster name to confirm deletion: try-01
→ deleting cluster try-01 …
  cluster try-01: destroying (0s)
  cluster try-01: deleted (1m21s)
deleted cluster try-01
removed cluster try-01 from capella.yaml (previous version kept as capella.yaml.bak)
```

Replace `<203.0.113.10/32>` with your machine's range: it is the one `capellactl cidr list try-01` shows, and differs
from the example. Each delete shows what goes, asks before deleting, and removes the item from `capella.yaml`. A cluster delete also
deletes its buckets, so `capellactl cluster delete try-01` alone is enough when you are sure. The project `sandbox`
stays: the next section uses it.

### Manage a provisioned cluster

These steps need a **provisioned cluster**, which Capella bills by the hour while it is on. Delete it when you are done
([Clean up](#clean-up)), or turn it off (step 16).

**11. Deploy a provisioned cluster**

```bash
capellactl cluster create dev-01 --project sandbox
```
```
Cluster type (free, provisioned) [provisioned]:
Cloud provider (aws, gcp, azure) [aws]: azure
Size (dev, small, medium, large, custom) [small]:
Region [eastus]:
Network CIDR (must not overlap other clusters) [10.0.0.0/24]:
Support plan (basic, developer pro, enterprise) [developer pro]:
New cluster dev-01 in project sandbox: azure eastus, 3 × 4 vCPU/16 GB, network 10.0.0.0/24, support developer pro

  + cluster dev-01  azure eastus · multi-AZ · 3 × 4 vCPU/16 GB · data,index,query · developer pro

Add dev-01 to capella.yaml and deploy it now? [y/N]: y
→ creating cluster dev-01 …
  cluster dev-01: deploying (0s) ...................
  cluster dev-01: healthy (9m40s)
connectionString (dev-01): couchbases://cb.xxxx.cloud.couchbase.com
Apply complete in 9m41s.
```

Sizes: `dev` (1 node, AWS only), `small` (3 × 4 vCPU/16 GB), `medium` (3 × 8/32), `large` (5 × 16/64) or `custom`.
Capella's API does not list the regions your organization can use: one it does not offer is rejected with Capella's
own message. Once you know the questions, you can answer them as options instead (`capellactl cluster create --help`);
this deploys the same cluster and asks only for the final `[y/N]`:

```bash
capellactl cluster create dev-01 --project sandbox --provider azure --region eastus --cidr 10.0.0.0/24 \
  --size small --support-plan "developer pro"
```

On AWS use `--provider aws --region us-east-1`, on Google Cloud `--provider gcp --region us-east1`; capellactl picks
each provider's disk type for you (Azure: Premium SSD, such as P6).

**12. Change a cluster**

A cluster can grow in two ways: **scale out** adds nodes of the same size, which adds capacity and spreads the load;
**scale up** replaces the nodes with bigger ones. Start by adding a node:

```bash
capellactl cluster scale dev-01 --nodes 4
```
```
  ~ cluster dev-01   scale out
      serviceGroups[data,index,query].numOfNodes:  3 → 4
```

Give each node more vCPUs and RAM (scale up), or change a setting such as the support plan:

```bash
capellactl cluster update dev-01 --cpu 8 --ram 32
capellactl cluster update dev-01 --support-plan enterprise     # or --description "…"
capellactl cluster update dev-01                               # no options: asks what to change
```

Each command shows the change, asks once, records it in `capella.yaml` and waits until the cluster is healthy again.
Even a description or support-plan change starts a short cluster job in Capella, so the command says so and waits.
Scaling in (fewer nodes or less RAM) is checked first: the buckets must still fit, and replicas need enough data
nodes (see [What is refused, and why](#what-is-refused-and-why)).

**13. Change and delete buckets, scopes and collections**

`dev-01` has no buckets yet. Create one with the settings a provisioned cluster allows (the free tier only took
`--memory`), and list before and after:

```bash
capellactl bucket list dev-01                                  # empty
capellactl bucket create dev-01 orders --memory 1024 --storage-backend magma --durability none
capellactl bucket list dev-01
```
```
S.NO  NAME    TYPE       STORAGE  MEMORY MB  REPLICAS  DURABILITY  TTL  ITEMS  IN FILE
1     orders  couchbase  magma    1024       1         none        0    0      yes
```

Give the bucket more memory. `bucket update` can also change replicas (extra copies of each document on other nodes),
durability, the bucket's document expiry (TTL) and whether it can be flushed (emptied):

```bash
capellactl bucket update dev-01 orders --memory 2048
```

Add a scope and a collection whose documents expire on their own. `--max-ttl` is the expiry in seconds: 2592000 is
30 days, `-1` never expires, and `0` uses the bucket's setting. Then change your mind and turn expiry off:

```bash
capellactl scope create dev-01 orders billing
capellactl collection create dev-01 orders billing invoices --max-ttl 2592000
capellactl collection update dev-01 orders billing invoices --max-ttl -1
```

Finally, practise deleting: a scope (with its collections and their documents), and a bucket made just for this:

```bash
capellactl scope delete dev-01 orders billing                  # asks you to type the scope name
capellactl bucket create dev-01 events --memory 1024
capellactl bucket delete dev-01 events                         # asks you to type the bucket name
```

Deletes show what goes (item count, collections, the credentials that lose access) and ask you to type the name.
Settings Capella cannot change after creation (bucket type, storage backend, …) are refused before anything changes.

**14. Rotate and remove app logins**

Good practice is to change (rotate) application passwords regularly, and to remove logins that are no longer used.
Create a login on `dev-01` as in step 9:

```bash
capellactl credential create dev-01 orders_app --privileges read+write --bucket orders --password-env ORDERS_APP_PASSWORD
```

To rotate, put the new password in the same environment variable and send it to Capella. Applications using the
login need the new password too:

```bash
export ORDERS_APP_PASSWORD='Orders-Passw0rd-2026-v2!'
capellactl credential update dev-01 orders_app --rotate-password
```

Remove the login when no application uses it any more:

```bash
capellactl credential delete dev-01 orders_app
```

Passwords are never compared, so nothing changes a password behind a running application except `--rotate-password`
(or `capellactl apply --rotate-passwords` for all of them). `capellactl help credentials` has the details.

**15. Protect a cluster from deletion**

Deletion protection is a Capella setting that stops a cluster from being deleted by mistake, by you, a colleague or a
script. Turn it on, see a delete refused, then turn it off again:

```bash
capellactl cluster protect dev-01 --on
capellactl cluster delete dev-01         # refused: deletion protection is on
capellactl cluster protect dev-01 --off
```

Protection blocks every way of deleting the cluster or its data (`cluster delete`, `bucket delete`, `scope delete`,
`project delete --cascade`, `destroy`, …) until you turn it off.

**16. Save money: power off, hibernation schedule, step scaling**

**Power off** stops the cluster's compute (its nodes) while keeping its data and settings: useful for a test cluster
you do not need right now. Turning it back on takes a few minutes:

```bash
capellactl cluster power dev-01 --off
capellactl cluster power dev-01 --on
```

A **hibernation schedule** lets Capella do this for you every week, for example on during office hours and off at
night and at weekends. `show` prints the weekly grid and the next on or off time:

```bash
capellactl cluster schedule set dev-01 --timezone US/Pacific --weekdays 08:00-18:00 --weekend off
capellactl cluster schedule show dev-01
```

For a late demo or an incident, **pause** the schedule so the cluster stays on, then **resume** it:

```bash
capellactl cluster schedule pause dev-01 --power-on
capellactl cluster schedule resume dev-01
```

**Step scaling** adds or removes one node at a time within limits you set, which suits a script or a scheduled job
that follows the load. At the limit it does nothing and still succeeds; removing a node is capacity-checked first:

```bash
capellactl cluster scale dev-01 --step +1 --max 6
capellactl cluster scale dev-01 --step -1 --min 3
```

The schedule is recorded in `capella.yaml`; power on/off is not (it is a moment, not a setting). While a cluster is
off, Capella does not allow changes to it or to its buckets: `plan` shows them as blocked and says when the schedule
turns it on again; `capellactl apply --power-on` turns it on first.

**17. Bring in changes made in the Capella UI**

`capella.yaml` is only up to date while changes go through capellactl. When someone changes Capella another way, in
the Capella UI or with another tool, `sync` reads Capella and updates the file to match. It never changes Capella.
Change something in the Capella UI, for example the cluster's description, then:

```bash
capellactl sync --dry-run    # show the difference only (exit 2 when out of date; good for CI)
capellactl sync              # update capella.yaml from Capella
```
```
--- capella.yaml (now)
+++ capella.yaml (from Capella)
-  description: Nova development cluster
+  description: changed in the Capella UI
capella.yaml updated from Capella (previous version kept as capella.yaml.bak).
```

`sync` only reads from Capella and keeps what Capella cannot return, such as `${ORDERS_APP_PASSWORD}`.
`capellactl sync --project sandbox` refreshes one project. A project or cluster renamed in the UI is recognised by its
`id:` and renamed in the file.

**18. Check for drift**

**Drift** is any difference between Capella and `capella.yaml`: a setting changed outside capellactl, something in
the file that is missing in Capella, or something in Capella that is not in the file (unmanaged). `drift` reports
it and changes nothing:

```bash
capellactl drift
```
```
Changed (capella.yaml differs from Capella; 'apply' changes Capella):
  ~ cluster dev-01
      description:  "changed in the Capella UI" → ""
      note: Capella runs a cluster update job for this (shown as "scale" in the Capella UI); nodes do not change

Unmanaged (in Capella, not in capella.yaml; 'apply --prune' deletes them, 'sync' adds them to the file):
    bucket dev-01/scratch

Drift: 1 changed, 0 missing, 1 unmanaged.
```

Each finding says how to resolve it: `apply` makes Capella match the file, `sync` makes the file match Capella. Run
it on a schedule, for example nightly in CI, to catch changes made outside capellactl; `--detailed-exitcode` makes it
exit with 2 when there is drift, so the job can alert you:

```bash
capellactl drift --detailed-exitcode
```

`drift`, `plan` and `sync` look alike: `plan` shows what `apply` would change in Capella, `sync` updates the file,
and `drift` only reports.

### Clean up

Delete the provisioned cluster, which stops the billing, then the project. Each asks you to type its name:

```bash
capellactl cluster delete dev-01                     # waits until it is gone (snapshot backups are kept)
capellactl project delete sandbox
```
```
  - cluster dev-01  azure eastus · 4 nodes · 1 bucket
    buckets deleted with the cluster: orders
    snapshot backups are kept (--discard-snapshots deletes them)
Type the cluster name to confirm deletion: dev-01
  cluster dev-01: destroying (0s)
  cluster dev-01: deleted (4m10s)
deleted cluster dev-01 (snapshot backups retained)
```

Each delete also removes the item from `capella.yaml`. If you skipped deleting the free-tier cluster, run
`capellactl cluster delete try-01` too. `project delete` refuses a project that still has clusters;
`capellactl project delete sandbox --cascade` deletes the clusters first.

### Build a whole environment in one go

You have now created each piece with its own command. capellactl can also take a description of a whole environment
(project, cluster, IP ranges, a bucket and an app login) and create all of it with one `apply`.

**19. Describe an environment with the wizard**

`init` writes a new `capella.yaml`, so start in a new folder:

```bash
mkdir ~/capella-nova && cd ~/capella-nova
capellactl init
```
```
Start from: a new environment, or an existing Capella project (new, import) [new]:
Organization: Nova Corp (6af0…)
Project (number of an existing project, or a new name): nova-dev
Project nova-dev does not exist yet; apply will create it.
Cluster name [nova-dev-01]:
Cloud provider (aws, gcp, azure) [aws]:
Region [us-east-1]:
Cluster network (must not overlap other clusters) [10.0.0.0/24]:
Size preset (dev, small, medium, large, custom) [small]:
Support plan (basic, developer pro, enterprise) [developer pro]:
Protect from deletion? [Y/n]:
Hibernate outside office hours (weekdays only)? [y/N]:
Allowed IP ranges (CIDR, comma-separated; empty: none):
Add a bucket now? Bucket name (empty: none):
✔ Wrote capella.yaml (validated)
Next: capellactl plan
```

`init` only reads from Capella (to list your organizations and projects). It writes a commented `capella.yaml`, never
the API key or a password (an app login gets `password: ${ORDERS_APP_PASSWORD}`), and asks before overwriting an
existing file (keeping a `.bak`).

**20. Check it, then create it**

Three commands take a file to a running environment. `validate` checks `capella.yaml` without contacting Capella
(field names, values, references between items). `plan` compares the file with Capella and lists what `apply` would
create or change. `apply` makes those changes, in order, and waits until the cluster is healthy:

```bash
capellactl validate
capellactl plan
capellactl apply
```
```
  + project nova-dev
  + cluster nova-dev-01  aws us-east-1 · multi-AZ · 3 × 4 vCPU/16 GB · data,index,query · developer pro  (after project is created)
  + deletion-protection nova-dev-01  deletionProtection: true  (after cluster is healthy)

Plan: 3 to add, 0 to change, 0 to delete, 0 blocked.
```

Run `apply` again and it reports `No changes`; if it stops halfway, fix the cause and run it again (finished steps are
not repeated). From here on, change the environment with the commands from steps 3–18, which keep this file up to date.

**21. The same without questions (scripts and CI)**

Every question in step 19 has an option. Once you know them, one command writes the file:

```bash
# AWS
capellactl init --non-interactive --project nova-dev --cluster nova-dev-01 --provider aws --region us-east-1 \
  --preset small --hibernation office-hours --timezone US/Pacific --cidr 203.0.113.10/32
# Azure (Azure disk types, such as P6, are chosen for you); for Google Cloud: --provider gcp --region us-east1
capellactl init --non-interactive --project nova-dev --cluster nova-dev-01 --provider azure --region eastus \
  --preset small --hibernation office-hours --timezone US/Pacific --cidr 203.0.113.10/32
capellactl init --dry-run     # print the YAML instead of writing it
```

`capellactl init --help` lists every option (bucket, app login, support plan, …); presets live in
`capellactl/config/presets.yaml`. In CI, set `CAPELLA_API_KEY` and `CAPELLA_ORG_ID` instead of running `configure`,
and add `--auto-approve` (`-y`) to commands that change something; `--quiet` keeps the log short.
`capellactl help ci` has GitHub Actions and GitLab CI examples.

**22. Copy a cluster to another region**

```bash
capellactl cluster clone nova-dev-01 nova-dev-west --region us-west-2                       # same project
capellactl project create nova-dr
capellactl cluster clone nova-dev-01 nova-dr-01 --region us-west-2 --to-project nova-dr --with-cidrs
capellactl cluster clone                                                                     # asks for everything
```

The copy gets the size, services, disks, support plan, deletion protection, and the buckets, scopes and collections.
Documents and the hibernation schedule are not copied; IP ranges and app logins only with `--with-cidrs` and
`--with-credentials` (each login gets a new password). The plan lists what is not copied before you confirm.

**23. Tear down and rebuild**

`apply` only creates and changes; it never deletes something just because it is missing from the file. To remove
buckets, scopes, logins and IP ranges that exist in Capella but not in `capella.yaml` (the unmanaged items `drift`
lists), add `--prune`:

```bash
capellactl apply --prune
```

`destroy` deletes everything `capella.yaml` describes, smallest items first, and keeps the file. Because the file
stays, `apply` can build the same environment again, which is handy for test environments you only need
sometimes:

```bash
capellactl destroy
capellactl apply
```

`destroy` refuses while a cluster has deletion protection, asks you to type the project name, keeps snapshot backups
unless `--discard-snapshots`, and keeps `capella.yaml`, so `apply` can build the environment again.

## What is refused, and why

`plan` and `apply` stop before changing anything when a change is unsafe or impossible:

```
  ! cluster dev-01  immutable: cloudProvider.region (requires a new cluster)
      cloudProvider.region:  "eastus" → "westus3"
      See: capellactl help idempotency
```

Fewer nodes, less RAM or a removed service group (scale-in) are checked first: the buckets must still fit in memory,
every bucket's replicas need enough data nodes, `data` can never be removed, and removing the last nodes of another
service or a whole group needs `--allow-service-removal` / `--allow-service-group-removal`:

```bash
capellactl cluster scale dev-01 --nodes 3
```
```
  ~ cluster dev-01   scale in
      serviceGroups[data,index,query].numOfNodes:  4 → 3
      checks: memory ok (1,024 / ~15,360 MB) · replicas ok (max 1, needs 2 data nodes)
```

Disks never shrink, and failed or degraded clusters are not changed. A turned-off cluster is powered on first
(`capellactl cluster power NAME --on`, or `apply --power-on`). `capellactl help safety` explains each case.

## When something goes wrong

- `configure` says "API Key Token rejected": the most common cause is the API key's **IP allowlist** (Capella UI →
  Organization settings → API Keys → your key) not including this machine's public IP
  (`curl -s https://checkip.amazonaws.com`). Also check that you copied the **API Key Token**, not the API Key ID. The
  message shows Capella's own hint and a `curl` command to test the key. To avoid pasting into the hidden prompt:
  `pbpaste | capellactl configure --api-key-stdin`.
- `import` or `configure` says `buckets and database credentials not imported (turnedOff)`: Capella does not return
  them while a cluster is off. Turn it on (`capellactl cluster power NAME --on`) and run `capellactl import` again.
- `plan` blocks a project with `probably renamed in Capella`: the project was renamed in the UI and the file has no
  `id:` for it. Run `capellactl sync` to adopt the new name (it also records the ids).
- `project NAME not found`: the `capella.yaml` in this folder is probably for another organization or project. Run
  `capellactl configure show` to see which file and organization are used; `capellactl import --force` rewrites the
  file for your organization (the old one is kept as `.bak`).
- Exit codes: `capellactl help exit-codes` (3 = config problem, 4 = blocked, 5 = timed out waiting).
- Details of every API call (secrets masked): `capellactl --log-level debug plan`.
- If `apply` stops halfway, fix the cause and run `capellactl apply` again; finished steps are not repeated.

For day-2 tasks with the exact command and expected output, see the [runbook](runbook.md).

## capella.yaml: written by capellactl

`capella.yaml` (`capella.yml` also works) describes all your projects and their clusters in one file. capellactl
creates it and keeps it up to date; you do not need to edit it.

| How it changes | Command |
|---|---|
| Created from your Capella projects | `capellactl configure` (offers it) or `capellactl import [--project NAME] [--cluster NAME]` |
| Created for a new environment | `capellactl init` |
| New project added | `capellactl project create NAME` |
| More existing projects added | `capellactl import` (adds the ones that are missing, leaves the others alone) |
| Cluster, bucket, scope, collection, IP range or app login added, changed or deleted | the matching `capellactl` command |
| Refreshed after changes made in the Capella UI | `capellactl sync` |

Keep it in version control to review changes over time. `capellactl help config <field>` explains any field you see
in it. Projects and clusters are recorded with their `id:`; to copy the file to another organization, delete the
`id:` lines first.
