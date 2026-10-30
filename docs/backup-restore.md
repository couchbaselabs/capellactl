# Backup and restore

This guide shows how to protect your data with `capellactl`: set backup schedules, take a backup before a risky
change, and restore a whole cluster or a single bucket. Everything is done with commands; you never edit
`capella.yaml`, and every schedule you set is recorded there so `plan`, `drift` and `sync` see it.

You need a working setup first (a profile, a `capella.yaml` and a provisioned cluster): follow
[Getting started](getting-started.md) up to "Manage a provisioned cluster". The examples use cluster `prod-01` in
project `sandbox`, its bucket `orders`, and a second cluster `prod-01-copy`. Free-tier clusters have no backups. Most
backup commands need an API key with the **Organization Owner** or **Project Owner** role.

- [Two kinds of backup](#two-kinds-of-backup)
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

To keep a copy in another region as well, add `--copy-to us-west-2` (AWS and Azure). Running the same command again
changes nothing. `capellactl cluster backup schedule delete prod-01` removes the schedule; existing backups are kept
until they expire.

## 3. Schedule bucket backups

With no options, the bucket gets a full backup every Sunday at 00:00 UTC and an incremental every 24 hours, kept for
30 days. Give only the values you want to change:

```bash
capellactl bucket backup schedule set prod-01 orders --start-at 2 --incremental-every 12
capellactl bucket backup schedule show prod-01 orders
```
```
weekly full on sunday at 02:00 UTC · incremental every 12 h · kept 30 days
```

| Option | Values |
|---|---|
| `--day` | `sunday` … `saturday` |
| `--start-at` | hour 0–23 (UTC) |
| `--incremental-every` | 1, 2, 4, 6, 8, 12, 24 hours |
| `--retention` | `30days`, `60days`, `90days`, `180days`, `1year` … `5years` |
| `--cost-optimized` | Capella's cost-optimized retention (`costOptimizedRetention`); off by default |

## 4. Back up now, before a change

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

Both wait until the backup is done (`--no-wait` returns at once).

## 5. List backups

Every list looks the same: a number first, the ID last.

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

`capellactl cluster backup list` without a cluster name shows the newest and oldest backup of every cluster in the
project; `capellactl bucket backup list prod-01 orders` shows every backup of one bucket. In the steps below, use an
ID from these lists in place of `CLUSTER_BACKUP_ID` or `BUCKET_BACKUP_ID`. To keep an important cluster backup longer:

```bash
capellactl cluster backup retain prod-01 CLUSTER_BACKUP_ID --retain 90d
```

## 6. Restore a bucket

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

A cluster restore replaces **all** data of the cluster with the backup, so you type the cluster name to confirm:

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

Capella packages the backup's whole cycle as a zip. The link is shown only in your terminal; for a new link later,
add `--export-id 9d78…` to the same command.

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
