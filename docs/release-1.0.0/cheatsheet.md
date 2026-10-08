# capellactl cheatsheet — 20-minute demo (Azure)

Copy-paste commands for everything that works in this build, written for Microsoft Azure: clusters deploy to Azure, with Azure region names (`eastus`, `westeurope`, not `us-east-1`) and Azure disk types (`P6`, `P10`, …). Part 1 is a timed demo script; Part 2 is the full reference. Every `create`/`update` shows the plan, asks once, records the change in `capella.yaml` and applies it. Add `--auto-approve` (before the command) to skip the question, or `--no-apply` (after it) to only record the change.

The demo uses **one project and one cluster**: `$PROJECT` and `$CLUSTER`, a single-node `dev` cluster. You create both before the demo (a cluster takes about 10 minutes to deploy); the demo then adds buckets, credentials, network rules and a hibernation schedule to them. Scaling needs more than one node, so section 8 uses a second, 3-node cluster `$SCALE_CLUSTER` (optional: it costs more while it runs).

## Set these once (every terminal)

```bash
source .venv/bin/activate                 # capellactl on PATH
export PROJECT=nova-demo                  # the demo project
export CLUSTER=nova-demo-01               # the demo cluster, in $PROJECT
export REGION=eastus                      # Azure region (eastus, eastus2, westeurope, centralindia …)
export BUCKET=demo                        # bucket created during the demo
export SCALE_CLUSTER=nova-demo-02         # optional 3-node cluster for the scaling demo (section 8)
export TZ_DEMO=US/Pacific                 # schedule timezone: US/Pacific, US/Eastern, Europe/London, Asia/Calcutta …
# Credential passwords: 8+ characters with an upper-case letter, a lower-case letter, a digit and a special
# character, and none of  < > ; . * & | £  (Capella's rules; capellactl checks them before sending).
export RO_PW='Demo-R3ad-2026!'            # password for demo_ro
export APP_PW='Demo-Passw0rd-2026!'       # password for demo_rw
export AIRLINE_PW='Demo-A1rline-2026!'    # password for airline_app
```

## Before the demo (the day before, ~15 minutes)

```bash
capellactl configure                      # paste the API Key Token; answer N to "write capella.yaml now?"
capellactl --auto-approve project create $PROJECT --description "Live demo"     # creates the project and capella.yaml
capellactl --auto-approve cluster create $CLUSTER --project $PROJECT --provider azure --region $REGION --size dev --support-plan "developer pro"
                                          # waits until the cluster is healthy (~10 min)
capellactl cluster get $CLUSTER           # state: healthy
# optional, for section 8 (scaling needs 3+ nodes): a small 3-node cluster
capellactl --auto-approve cluster create $SCALE_CLUSTER --project $PROJECT --provider azure --region $REGION --size small --support-plan "developer pro"
capellactl plan                           # must end with "0 to add, 0 to change, 0 to delete, 0 blocked"
```

The API key needs **Project Owner** or **Project Manager** on `$PROJECT` (a project it can only view fails with `Access Denied`). If the Capella UI was used since (renames too), run `capellactl sync` before the demo.

---

# Part 1 — the demo (15 minutes)

### 1. What exists (1 min)

```bash
capellactl project list                   # IN FILE column: what capella.yaml manages ($PROJECT)
capellactl cluster options                # what can be deployed: free tier vs provisioned, sizes, regions
capellactl cluster list --project $PROJECT
capellactl cluster get $CLUSTER           # Azure region, size, state, connection string
grep -n "$CLUSTER" -A10 capella.yaml      # the cluster as code: recorded by 'cluster create', never edited by hand
```

### 2. Bucket, scope, collections (3 min)

On a single-node cluster (`--size dev`, like `$CLUSTER`) buckets get 0 replicas automatically; leave out `--replicas` and `--durability`. On a free-tier cluster only `--memory` can be set.

```bash
capellactl bucket create $CLUSTER $BUCKET --memory 256 --storage-backend magma
capellactl scope create $CLUSTER $BUCKET inventory
capellactl collection create $CLUSTER $BUCKET inventory airline
capellactl collection create $CLUSTER $BUCKET inventory route --max-ttl 86400
capellactl bucket list $CLUSTER
capellactl collection list $CLUSTER $BUCKET inventory
capellactl bucket update $CLUSTER $BUCKET --memory 512
```

### 3. Database credentials, least privilege (3 min)

Every credential gets its password from an environment variable set above (`--password-env VAR`): the value is
never typed on the command line, and capella.yaml records only `${VAR}`.

```bash
# whole bucket (demo.*.*), read-only; password = $RO_PW
capellactl credential create $CLUSTER demo_ro --privileges read --bucket $BUCKET --password-env RO_PW

# one scope (demo.inventory.*), read+write; password = $APP_PW
capellactl credential create $CLUSTER demo_rw --privileges read+write --bucket $BUCKET --scope inventory --password-env APP_PW

# one collection (demo.inventory.airline), read+write; password = $AIRLINE_PW
capellactl credential create $CLUSTER airline_app --privileges read+write --bucket $BUCKET --scope inventory --collection airline --password-env AIRLINE_PW

capellactl credential list $CLUSTER
capellactl credential get $CLUSTER airline_app             # access and password source (${AIRLINE_PW}), never the value

# rotate: set the new value, then rotate; Capella gets the new $AIRLINE_PW
export AIRLINE_PW='Demo-A1rline-2026-v2!'
capellactl credential update $CLUSTER airline_app --rotate-password
```

### 4. It's all code: plan, idempotency, capella.yaml (2 min)

```bash
capellactl plan                           # "0 to add, 0 to change": Capella matches the file
capellactl validate                       # offline check, no API calls
grep -n "$BUCKET" -A12 capella.yaml       # everything above was recorded; passwords appear as ${RO_PW}, ${APP_PW}, ${AIRLINE_PW}, never values
capellactl apply                          # nothing to do, zero writes
```

### 5. Safety: who can connect, deletion protection (2 min)

```bash
capellactl cidr create $CLUSTER $(curl -s https://api.ipify.org)/32 --comment "Demo laptop"
capellactl cidr list $CLUSTER
capellactl cluster protect $CLUSTER --on
capellactl bucket delete $CLUSTER $BUCKET                  # refused: the cluster has deletion protection
capellactl cluster protect $CLUSTER --off
```

### 6. Change the cluster (1 min)

```bash
capellactl cluster update $CLUSTER --description "Nova demo cluster"   # the plan notes Capella runs a cluster job ("scale" in the UI); nodes do not change
capellactl cluster get $CLUSTER
```

### 7. Hibernation schedule: off outside working hours (2 min)

Pick an on-window that includes the demo time in `$TZ_DEMO`, or the schedule turns the cluster off mid-demo.

```bash
capellactl cluster schedule set $CLUSTER --timezone $TZ_DEMO --weekdays 07:00-20:00 --weekend off
capellactl cluster schedule set $CLUSTER --friday 07:00-15:00              # per-day override; only Friday changes
capellactl cluster schedule show $CLUSTER                                  # weekly grid and "Next: off at …"
grep -n "hibernation" -A5 capella.yaml                                     # recorded as code
capellactl cluster schedule pause $CLUSTER                                 # demo or incident: stays as it is until resumed
capellactl cluster schedule resume $CLUSTER                                # prints the next on/off time
```

### 8. Scale with guardrails (2 min, needs `$SCALE_CLUSTER`)

```bash
capellactl cluster scale $SCALE_CLUSTER --step +1 --max 4                  # 3 → 4 nodes
capellactl cluster scale $SCALE_CLUSTER --step +1 --max 4                  # "already at maximum (4)": exit 0, nothing changes
capellactl cluster scale $SCALE_CLUSTER --nodes 3                          # scale in: "checks: memory ok … · replicas ok …" before it asks
capellactl --auto-approve -o json cluster scale $SCALE_CLUSTER --step -1 --min 3   # for scripts/alerts: {"status": "at_limit", …}
capellactl cluster scale $CLUSTER --step +1                                # single-node dev cluster: "already at maximum (1)"
```

A scale-in is refused when the buckets would not fit in memory or a bucket's replicas would lack data nodes, and it never removes the last data nodes. Each scale takes several minutes; dots show progress every 30 s.

### 9. Drift: what changed outside capellactl (2 min)

Before this step, change something by hand in the Capella UI, for example add a bucket `scratch` to `$CLUSTER`.

```bash
capellactl drift                          # Changed / Missing / Unmanaged: "bucket nova-demo-01/scratch" is unmanaged
capellactl drift --detailed-exitcode; echo "exit $?"     # CI: 2 = drift
capellactl apply --prune                  # deletes the unmanaged bucket (type its name to confirm); clusters are never pruned
capellactl drift                          # "No drift"
```

### 10. Stop paying when idle: power off (1 min)

```bash
capellactl --no-wait cluster power $CLUSTER --off          # shows what is kept (storage, data, users, allow lists) and asks
capellactl cluster get $CLUSTER                            # state: turningOff → turnedOff after a few minutes
capellactl plan                                            # changes below a turned-off cluster are blocked ("…--power-on")
capellactl cluster power $CLUSTER --on                     # waits until healthy (or later: apply --power-on)
```

### 11. Tear it all down, rebuild it from the file (optional, end of the demo)

```bash
capellactl cluster protect $CLUSTER --off                  # destroy refuses while protection is on
capellactl destroy                                         # deletes everything capella.yaml declares, children first; type $PROJECT to confirm
capellactl apply                                           # capella.yaml was kept: builds the same environment again (~10 min)
```

### If a command fails

If Capella rejects a create/update outright (a bad value, a Capella rule), nothing is recorded: `capella.yaml` is restored, so run the same command again with corrected values (for example the right Azure region). Re-running `cluster create $CLUSTER` also replaces a cluster that is in the file but was never deployed. Only when part of the change reached Capella is the file kept ahead of it; then:

```bash
capellactl plan                           # what is still missing in Capella
capellactl apply                          # finish it; completed steps are not repeated
```

| Message | What to do |
|---|---|
| `… is not an azure region name; it looks like an aws region` | Use an Azure region: `--region eastus` (not `us-east-1`) |
| `capella.yaml was restored` | Capella refused the values; nothing changed. Correct them and run the same command again |
| `Access Denied … required role` | Give the API key Project Owner/Manager on `$PROJECT` |
| `probably renamed in Capella` | `capellactl sync` (adopts the new name), or rename it back in the UI |
| `project … not found` | `$PROJECT` does not exist yet: run the "Before the demo" steps |
| `NAME is a cluster in project P, not a project` | You passed `$CLUSTER` where `$PROJECT` was expected |

### Reset after the demo (keep the cluster for next time)

```bash
capellactl cluster power $CLUSTER --on                    # if it was left off
capellactl --auto-approve cluster schedule delete $CLUSTER
capellactl --auto-approve credential delete $CLUSTER airline_app
capellactl --auto-approve credential delete $CLUSTER demo_rw
capellactl --auto-approve credential delete $CLUSTER demo_ro
capellactl --auto-approve bucket delete $CLUSTER $BUCKET
capellactl cidr delete $CLUSTER $(curl -s https://api.ipify.org)/32
```

### Remove everything (start fresh)

```bash
capellactl cluster protect $CLUSTER --off                 # only if protection was left on
capellactl --auto-approve destroy --discard-snapshots     # deletes everything in capella.yaml; the file is kept (apply rebuilds it)
# or, removing them from capella.yaml too:
capellactl --auto-approve project delete $PROJECT --cascade --discard-snapshots
```

---

# Part 2 — full reference (everything that works today)

### Setup & profiles

```bash
capellactl configure                                      # save API Key Token (OS keychain) + organization
capellactl configure --profile prod                       # a second profile
capellactl configure list
capellactl configure show                                 # effective settings and where each comes from
capellactl --profile prod project list                    # use a profile for one command
pbpaste | capellactl configure --api-key-stdin            # macOS: no hidden-prompt paste
```

### capella.yaml: create, import, sync, plan, apply

```bash
capellactl init                                           # wizard: writes a new capella.yaml
capellactl init --dry-run                                 # print the YAML only
capellactl import                                         # write existing projects/clusters to capella.yaml (read-only)
capellactl import --project $PROJECT --cluster $CLUSTER
capellactl sync                                           # refresh capella.yaml after changes made in the Capella UI
capellactl sync --dry-run                                 # show differences; exit 2 when out of date (CI)
capellactl validate
capellactl plan
capellactl plan --target cluster/$CLUSTER
capellactl apply
capellactl apply --target cluster/$CLUSTER
capellactl apply --prune                                  # also delete what is in Capella but not in the file (asks)
capellactl apply --rotate-passwords                       # rotate every credential (sends its ${VAR} value)
capellactl apply --power-on                               # turn on a turned-off cluster before changing it
capellactl -o json plan --detailed-exitcode               # JSON output; exit 2 when there are changes
capellactl drift                                          # changed, missing and unmanaged resources (read-only)
capellactl drift --detailed-exitcode                      # CI: exit 2 on drift
capellactl -o json drift
capellactl destroy                                        # delete everything the file declares (type the project name)
capellactl destroy --discard-snapshots
```

### Projects

```bash
capellactl project list
capellactl project get $PROJECT
capellactl project create $PROJECT --description "Live demo"
capellactl project update $PROJECT --description "Nova demo"
capellactl project delete $PROJECT                    # refused while it has clusters
capellactl project delete $PROJECT --cascade          # deletes its clusters first
```

### Clusters

```bash
capellactl cluster options                                # what you can deploy (free tier, sizes, regions)
capellactl cluster list
capellactl cluster get $CLUSTER
# create: each line is an alternative way to deploy $CLUSTER (a name can exist once per project)
capellactl cluster create $CLUSTER --project $PROJECT --provider azure   # asks size, region, network, support plan
capellactl cluster create $CLUSTER --project $PROJECT --free-tier --provider azure --region eastus   # free tier on Azure: eastus, swedencentral, koreacentral
capellactl cluster create $CLUSTER --project $PROJECT --provider azure --region $REGION --size medium --support-plan enterprise
capellactl cluster create $CLUSTER --project $PROJECT --provider azure --region westeurope --size small --disk-type P10
capellactl cluster update $CLUSTER --support-plan enterprise
capellactl cluster update $CLUSTER --description "Nova dev"
capellactl cluster update $CLUSTER --cpu 8 --ram 32       # bigger nodes; less RAM runs the memory check; multi-node clusters
capellactl cluster scale $SCALE_CLUSTER --nodes 4         # scale out; multi-node clusters (a --size dev cluster stays 1 node)
capellactl cluster scale $SCALE_CLUSTER --nodes 3         # scale in: memory and replica checks first
capellactl cluster scale $SCALE_CLUSTER --nodes 2 --group search
capellactl cluster scale $SCALE_CLUSTER --step +1 --max 6                 # one node more; exit 0 at the limit
capellactl cluster scale $SCALE_CLUSTER --step -1 --min 3                 # one node less, capacity-checked
capellactl cluster scale $SCALE_CLUSTER --step +1 --all-groups            # each group +1 on its own
capellactl --auto-approve -o json cluster scale $SCALE_CLUSTER --step +1  # {"cluster","group","from","to","status"}
capellactl apply --allow-service-removal --allow-service-group-removal    # after removing a group from the file
capellactl cluster power $CLUSTER --off                   # stop compute; storage, data and settings stay
capellactl cluster power $CLUSTER --on
capellactl cluster power $CLUSTER --on --with-app-service
capellactl cluster protect $CLUSTER --on
capellactl cluster protect $CLUSTER --off
capellactl cluster delete $CLUSTER                    # type the name to confirm; snapshots kept
capellactl cluster delete $CLUSTER --discard-snapshots
```

Sizes: `dev` (1 node), `small` (3 × 4 vCPU/16 GB), `medium` (3 × 8/32), `large` (5 × 16/64), `custom` (`--nodes --cpu --ram`).

Migrating from `scale_capella_cluster.sh`: [migrating-from-scale-script.md](../migrating-from-scale-script.md).

### Hibernation schedule

```bash
capellactl cluster schedule set $CLUSTER --timezone $TZ_DEMO --weekdays 08:00-18:00 --weekend off
capellactl cluster schedule set $CLUSTER --friday 08:00-14:30    # per-day override (--monday … --sunday)
capellactl cluster schedule set $CLUSTER --wednesday on          # on all day
capellactl cluster schedule show $CLUSTER                        # weekly grid + next transition (-o json: nextTransition)
capellactl cluster schedule pause $CLUSTER --power-on            # keep it on (and turn it on if it is off)
capellactl cluster schedule resume $CLUSTER
capellactl cluster schedule apply $CLUSTER                       # apply only what capella.yaml records
capellactl cluster schedule delete $CLUSTER                      # removes it from Capella and capella.yaml
```

Windows are `HH:MM-HH:MM` with minutes `00` or `30` (`24:00` = end of day); a day is `on`, `off` or a window; a week cannot be off every day.

Azure disks: the disk type sets the size (`P6` default, `P10`, `P15`, `P20`, `P30` … `P60`, `Ultra`); choose it with `--disk-type` at create. `--disk-size` and `--disk-iops` are for AWS/GCP disks. On another provider, use `--provider aws --region us-east-1` or `--provider gcp --region us-east1`.

### Allowed IP ranges

```bash
capellactl cidr list $CLUSTER
capellactl cidr create $CLUSTER 203.0.113.10/32 --comment "Office VPN"
capellactl cidr create $CLUSTER 198.51.100.0/24 --expires-at 2026-12-31T23:59:59Z
capellactl cidr delete $CLUSTER 203.0.113.10/32
```

### Buckets

```bash
capellactl bucket list $CLUSTER
capellactl bucket get $CLUSTER $BUCKET
capellactl bucket create $CLUSTER $BUCKET --memory 1024 --storage-backend magma --durability majority   # multi-node clusters
capellactl bucket create $CLUSTER sessions --type ephemeral --memory 256 --eviction-policy nruEviction
capellactl bucket update $CLUSTER $BUCKET --memory 2048
capellactl bucket update $CLUSTER $BUCKET --replicas 2 --durability majority --ttl 0 --flush   # multi-node clusters; single-node: replicas 0
capellactl bucket delete $CLUSTER $BUCKET                 # type the name to confirm
```

### Scopes & collections

```bash
capellactl scope list $CLUSTER $BUCKET
capellactl scope create $CLUSTER $BUCKET billing
capellactl scope delete $CLUSTER $BUCKET billing          # deletes its collections and documents
capellactl collection list $CLUSTER $BUCKET billing
capellactl collection create $CLUSTER $BUCKET billing invoices --max-ttl 2592000   # -1 never expire, 0 bucket TTL
capellactl collection create $CLUSTER $BUCKET _default legacy
capellactl collection update $CLUSTER $BUCKET billing invoices --max-ttl -1        # Server 7.6.0+
capellactl collection delete $CLUSTER $BUCKET billing invoices
```

### Database credentials

| Access | Flags |
|---|---|
| `bucket.*.*` | `--bucket B` |
| `bucket.scope.*` | `--bucket B --scope S` |
| `bucket.scope.collection` | `--bucket B --scope S --collection C` (repeat `--collection`) |
| every bucket | `--all-buckets` |

Privileges: `--privileges read` (default), `write` or `read+write`. Password: always pass one, `--password-env VAR` (from an environment variable) or `--password-file PATH` (from a file); capella.yaml records `${VAR}` or `${file:PATH}`, never the value, and the password is never typed on the command line. Rules: 8+ characters with upper-case, lower-case, digit and special character, none of `< > ; . * & | £`. (Without a password flag, Capella generates a random password and capellactl saves it to `.capellactl/credentials/CLUSTER.NAME.json`; read it with `jq -r .password` on that file.)

```bash
capellactl credential list $CLUSTER
capellactl credential get $CLUSTER demo_ro
capellactl credential create $CLUSTER demo_ro --bucket $BUCKET --password-env RO_PW
capellactl credential create $CLUSTER demo_rw --privileges read+write --bucket $BUCKET --scope inventory --password-env APP_PW
capellactl credential create $CLUSTER airline_app --privileges read+write --bucket $BUCKET --scope inventory --collection airline --collection route --password-env AIRLINE_PW
capellactl credential create $CLUSTER dba --privileges read+write --all-buckets --password-file ./secrets/dba.pw
capellactl credential update $CLUSTER demo_ro --privileges read+write --bucket $BUCKET   # replaces its access
capellactl credential update $CLUSTER demo_ro --rotate-password                          # sends the current $RO_PW
capellactl credential update $CLUSTER demo_ro --password-env APP_PW --rotate-password    # switch to $APP_PW and send it
capellactl credential delete $CLUSTER demo_ro
```

### Help

```bash
capellactl help topics                    # getting-started, config, idempotency, scaling, credentials, safety …
capellactl help credentials
capellactl credential create --help       # every command has --help with examples
capellactl help exit-codes                # 3 config problem, 4 blocked, 5 timed out
capellactl --log-level debug plan         # every API call, secrets masked
```

## Status

Current status of every command: [API-COVERAGE.md](API-COVERAGE.md).
