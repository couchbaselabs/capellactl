# Backup and restore

This guide shows how to protect your data with `capellactl`: set backup schedules, take a backup before a risky
change, and restore a whole cluster or a single bucket. Everything is done with commands; you never edit
`capella.yaml`, and every schedule you set is recorded there so `plan`, `drift` and `sync` see it.

You need a working setup first (a profile, a `capella.yaml` and a provisioned cluster): follow
[Getting started](getting-started.md) up to "Manage a provisioned cluster". The examples use cluster `prod-01` in
project `sandbox`, its bucket `orders`, and a second cluster `prod-01-copy`. Free-tier clusters have no backups. Most
backup commands need an API key with the **Organization Owner** or **Project Owner** role.

- [Two kinds of backup](#two-kinds-of-backup)
- [Options every backup command takes](#options-every-backup-command-takes)
- [1. See what your plan allows](#1-see-what-your-plan-allows)
- [2. Schedule cluster backups](#2-schedule-cluster-backups)
- [3. Schedule bucket backups](#3-schedule-bucket-backups)
- [4. Back up now, before a change](#4-back-up-now-before-a-change)
- [5. List backups](#5-list-backups)
- [6. Restore a bucket](#6-restore-a-bucket)
- [7. Restore a whole cluster](#7-restore-a-whole-cluster)
- [8. Download a bucket backup](#8-download-a-bucket-backup)
- [9. What capella.yaml records](#9-what-capellayaml-records)
- [Troubleshooting](#troubleshooting)

## Two kinds of backup

| | Cluster backup (`cluster backup …`) | Bucket backup (`bucket backup …`) |
|---|---|---|
| Capella name | Cloud snapshot backup | Backup (bucket) |
| What is saved | The whole cluster: every bucket, index and setting, at the cloud-disk level | One bucket's data: a weekly **full** backup starts a **cycle**, then **incrementals** every few hours |
| Schedule | Every N hours, kept for a number of hours or days, optional copies in up to two other regions | Day and hour of the weekly full backup, incremental interval, retention from 30 days to 5 years |
| Restore | Replaces all data of the same cluster | To the same or another cluster, all of it or selected scopes and collections |
| Use it for | Recovering a cluster after a bad change or an outage | Recovering one bucket, copying a bucket to another cluster, keeping data for years |

## Options every backup command takes

Each step below lists the options of its own commands. These ones work the same way everywhere, so they are explained
only here:

| Option | Default | Meaning |
|---|---|---|
| `NAME` / `CLUSTER` | required | The cluster, by its name in `capella.yaml` or in Capella |
| `BUCKET` | required where shown | The bucket of that cluster |
| `--project` | the cluster's project | Only needed when two projects have a cluster with that name |
| `--no-apply` | off | `schedule set` only: record the schedule in `capella.yaml` without sending it; `capellactl apply` sends it later |
| `--no-wait` | off | A global option, given before the command (`capellactl --no-wait cluster backup create prod-01`): return as soon as Capella accepts the request instead of waiting for the backup, restore or export |
| `--auto-approve` | off | A global option: answer yes to the question, including typing the name for a restore or delete. Use it only in scripts that should not stop to ask |
| `--timeout` | `60m` | A global option: how long to wait before giving up. The backup carries on in Capella |

## 1. See what your plan allows

The backup intervals and retention a cluster can use depend on its support plan, so ask Capella first:

```bash
capellactl cluster backup schedule options prod-01
```
```
Cluster backup schedule options for prod-01 (support plan: developer pro)
  every (hours)   1, 2, 4, 6, 8, 12, 24
  keep            1 day to 90 days
  copy regions    us-east-2, us-west-2, eu-west-1 (up to two)
```

## 2. Schedule cluster backups

A cluster has one backup schedule. `schedule set` creates it or changes it:

| Option | Default | Meaning |
|---|---|---|
| `--every` | required for a new schedule | Hours between backups. Use a value from step 1 |
| `--retain` | required for a new schedule | How long each backup is kept, in hours or days: `720`, `720h` or `30d`. It must be within the "keep" range from step 1 |
| `--start` | Capella's | Time of day of the first backup, `HH:MM` in UTC. Later backups follow every `--every` hours |
| `--copy-to` | no copies | A region to keep a copy of every backup in, from the "copy regions" in step 1. Repeat it for a second region; two at most. Copies let you restore when the cluster's own region is unavailable |
| `--no-copies` | off | Stop keeping copies in other regions |

To change a schedule, give only the options you want to change, for example `--retain 90d`. Options you leave out
keep their current values.

```bash
capellactl cluster backup schedule set prod-01 --every 24 --retain 30d --start 02:00
capellactl cluster backup schedule show prod-01
```
```
  + backup-schedule prod-01  every 24 h · kept 30 days · first at 02:00 UTC

Plan: 1 to add, 0 to change, 0 to delete, 0 blocked.
Record this backup schedule in capella.yaml and apply it to prod-01? [y/N]: y

every 24 h · kept 30 days · first at 02:00 UTC
next backup: 2026-10-30 02:00 UTC
```

Running the same command again changes nothing. `capellactl cluster backup schedule delete prod-01` removes the schedule; existing backups are kept
until they expire.

## 3. Schedule bucket backups

Bucket backups run in weekly **cycles**: a full backup on one day of the week, then incremental backups (only what
changed since the previous backup) every few hours until the next full backup. `schedule set` takes:

| Option | Default | Meaning |
|---|---|---|
| `--day` | `sunday` | Day of the weekly full backup, which starts a new cycle: `sunday` … `saturday` |
| `--start-at` | `0` | Hour of the day, 0–23 in UTC, when the backups start |
| `--incremental-every` | `24` | Hours between incremental backups: 1, 2, 4, 6, 8, 12 or 24 |
| `--retention` | `30days` | How long backups are kept: `30days`, `60days`, `90days`, `180days`, `1year` … `5years` |
| `--cost-optimized` / `--no-cost-optimized` | off | Capella's cost-optimized retention, which keeps fewer backups of older cycles at a lower cost |

On a terminal, without options, `schedule set` asks for each value with the default shown. Give only the options you
want to change:

```bash
capellactl bucket backup schedule set prod-01 orders --start-at 2 --incremental-every 12
capellactl bucket backup schedule show prod-01 orders
```
```
weekly full on sunday at 02:00 UTC · incremental every 12 h · kept 30 days
```

`capellactl bucket backup schedule delete prod-01 orders` removes the schedule; existing backups are kept until they
expire.

## 4. Back up now, before a change

A backup you take now is kept apart from the scheduled ones. `cluster backup create` takes:

| Option | Default | Meaning |
|---|---|---|
| `--retain` | Capella's | How long to keep this backup, in hours or days: `168` or `7d` |
| `--copy-to` | no copies | A region to keep a copy in (repeatable, two at most), as for the schedule |

`bucket backup create prod-01 orders` has no options of its own. It adds a backup to the bucket's current cycle, or
starts a cycle when there is none.

```bash
capellactl cluster backup create prod-01
capellactl bucket backup create prod-01 orders
```
```
→ backing up cluster prod-01 …
  backup of prod-01: pending (0s)
  backup of prod-01: complete (6m10s)
backup 3f1c… of prod-01 is complete
```

Both wait until the backup is done, showing its status with a dot every 30 seconds.

## 5. List backups

Every list looks the same: a number first, the ID last. The `list` commands have no options besides the shared ones;
what they show depends on the names you give:

| Command | Shows |
|---|---|
| `cluster backup list` | The newest and oldest backup of every cluster, in every project of `capella.yaml` (`--project` for one) |
| `cluster backup list prod-01` | Every backup of the cluster |
| `bucket backup list prod-01` | The latest backup of each bucket of the cluster |
| `bucket backup list prod-01 orders` | Every backup of the bucket |
| `bucket backup cycle list prod-01 orders` | The bucket's weekly cycles; `cycle get prod-01 orders CYCLE_ID` lists the backups of one |
| `bucket backup get prod-01 BUCKET_BACKUP_ID` | One backup with its statistics |

```bash
capellactl cluster backup list prod-01
capellactl bucket backup list prod-01
capellactl bucket backup cycle list prod-01 orders
```
```
S.NO  CREATED           TYPE       STATUS    SIZE   EXPIRES           COPIES  ID
1     2026-10-29 10:12  onDemand   complete  42 GB  2026-11-28 10:12  -       3f1c…
2     2026-10-28 02:00  scheduled  complete  41 GB  2026-11-27 02:00  -       9b07…

S.NO  BUCKET  DATE              METHOD  SOURCE     STATUS  SIZE    ITEMS    EXPIRES           ID
1     orders  2026-10-29 10:20  full    manual     ready   3.1 GB  912,000  2026-11-28 10:20  7a2e…
```

In the steps below, use an ID from these lists in place of `CLUSTER_BACKUP_ID` or `BUCKET_BACKUP_ID`. To keep an
important cluster backup longer (or shorter), `retain` sets a new `--retain`, counted from when the backup was taken:

```bash
capellactl cluster backup retain prod-01 CLUSTER_BACKUP_ID --retain 90d
```

## 6. Restore a bucket

`bucket backup restore CLUSTER BUCKET_BACKUP_ID` restores the backup's bucket. Without options it restores all the
bucket's data into the same bucket of the same cluster, and keeps documents that are newer in the cluster. The options
change where it goes, what is restored and how:

| Option | Default | Meaning |
|---|---|---|
| `--to-cluster` | the backup's cluster | Restore into another cluster of the same project |
| `--services` | `data` | What to restore: `data` (documents), `query` (index definitions), or `data,query` |
| `--include-data` | everything | Restore only these, comma-separated: `orders` (a bucket), `orders.sales` (a scope), `orders.sales.2026` (a collection) |
| `--exclude-data` | nothing | Skip these, in the same form |
| `--map-data` | none | Restore into a different bucket, scope or collection: `orders.sales=orders.sales_check`, comma-separated |
| `--filter-keys` | all documents | Restore only documents whose key matches this regular expression |
| `--filter-values` | all documents | Restore only documents whose value matches this regular expression |
| `--replace-ttl` | not set (Capella's) | Document expiry: `none` keeps the expiry each document had, `all` gives every document a new one, `expired` gives a new one only to documents that have expired since the backup |
| `--replace-ttl-with` | none | The new expiry for `--replace-ttl all` or `expired`, as a date and time (`2027-01-01T00:00:00Z`) |
| `--force-updates` | off | Overwrite documents even when the cluster's copy is newer than the backup's |
| `--auto-remove-collections` | off | Delete scopes and collections that had been deleted when the backup was taken |

The safest restore puts the backup back into the same bucket, keeps documents that are newer in the cluster, and
leaves document expiry as it was:

```bash
capellactl bucket backup restore prod-01 BUCKET_BACKUP_ID --replace-ttl none
```
```
  ~ restore orders from the backup of 2026-10-29 10:20 UTC into prod-01
    services: data · newer documents in prod-01 are kept
Type the target cluster name to confirm the restore: prod-01
restore of orders into prod-01 started; Capella reports its progress in the cluster's activity log (the Management API has no restore status for bucket backups)
```

Restore only one collection into another cluster, for example to check data before touching production:

```bash
capellactl bucket backup restore prod-01 BUCKET_BACKUP_ID --to-cluster prod-01-copy --include-data orders.sales
```

## 7. Restore a whole cluster

A cluster restore replaces **all** data of the cluster with the backup, so you type the cluster name to confirm. It
has one option:

| Option | Default | Meaning |
|---|---|---|
| `--from-region` | the backup itself | A region holding a copy of the backup (from `--copy-to`), to use if the backup itself cannot be restored. Repeat it to give a second region; they are tried in order |

The cluster must be on; `capellactl cluster backup restores prod-01` lists past restores and
`capellactl cluster backup regions prod-01` the regions copies can go to.

```bash
capellactl cluster backup restore prod-01 CLUSTER_BACKUP_ID
capellactl cluster backup restores prod-01
```
```
  ± cluster prod-01  all data is replaced with the backup of 2026-10-29 10:12 UTC
Type the cluster name to confirm the restore: prod-01
→ restoring cluster prod-01 …
  restore of prod-01: complete (12m30s)
  cluster prod-01: healthy (13m02s)
restored cluster prod-01 from the backup of 2026-10-29 10:12 UTC
```

## 8. Download a bucket backup

`export` packages the backup's whole cycle as a zip in Capella and prints a link to download it. Capella allows one
export per cycle, so its only option shows an earlier one:

| Option | Default | Meaning |
|---|---|---|
| `--export-id` | start a new export | Show an export started earlier: its status and a new download link |

```bash
capellactl bucket backup export prod-01 BUCKET_BACKUP_ID
```
```
export 9d78… of orders started
  export of orders: complete (4m20s)
export 9d78… is complete: 3.1 GB, available until 2026-10-29 22:00 UTC
download (valid for one hour; treat it like a password):
  https://…
```

The link is shown only in your terminal. For a new link later, add `--export-id 9d78…` to the same command.

## 9. What capella.yaml records

Schedules are part of your environment; backups themselves are not.

```yaml
clusters:
  - name: prod-01
    backupSchedule:            # cluster backups
      interval: 24
      retention: 720
      startTime: "02:00"
    buckets:
      - name: orders
        backupSchedule:        # bucket backups
          dayOfWeek: sunday
          startAt: 2
          incrementalEvery: 12
          retentionTime: 30days
          costOptimizedRetention: false
```

`capellactl drift` reports a schedule someone changed in the Capella UI, and `capellactl sync` records it.
Without a `backupSchedule` key, an existing schedule is left alone; `capellactl apply --prune` deletes it.

## Troubleshooting

| Message | What to do |
|---|---|
| `interval 3 is not permitted: use one of 1, 2, 4, 6, 8, 12, 24 hours …` | Pick a value from `cluster backup schedule options` |
| `free-tier clusters have no backups` | Create a provisioned cluster for data that needs backups |
| `turned off; power it on before restoring` | `capellactl cluster power prod-01 --on`, then restore |
| `backup … not found` | List the backups again; a backup past its retention is deleted by Capella |
| `deletes cycle … with 7 backups` | Deleting a bucket backup deletes its whole weekly cycle; take a new backup first if you still need one |
| `already has an export (Capella allows one per cycle)` | Show the earlier export with `--export-id ID` |
| `backup schedules not read: the API key needs the Organization Owner or Project Owner role` | `sync` kept the schedules capella.yaml has; use a key with one of those roles to read them |
