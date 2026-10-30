# Backup and restore

Capella has two kinds of backup, and capellactl manages both:

| | Cluster backup | Bucket backup |
|---|---|---|
| Commands | `capellactl cluster backup …` | `capellactl bucket backup …` |
| Capella name | Cloud snapshot backup | Backup (bucket) |
| What is saved | The whole cluster: every bucket, index and setting | One bucket: a weekly **full** backup starts a **cycle**, then **incrementals** |
| Schedule | `cluster backup schedule set NAME --every HOURS --retain 30d [--start HH:MM] [--copy-to REGION]` | `bucket backup schedule set CLUSTER BUCKET [--day sunday --start-at 2 --incremental-every 24 --retention 30days]` |
| Restore | Replaces all data of the same cluster | Same or another cluster, all of it or selected scopes and collections |

**Schedules are part of the environment.** `schedule set` records `backupSchedule` in capella.yaml (on the cluster,
or on the bucket) and applies it; `plan`, `apply`, `drift` and `sync` include it, and `apply --prune` deletes a
schedule the file no longer declares. Without a `backupSchedule` key, an existing schedule is left alone. The
intervals and retention a cluster may use depend on its support plan: `cluster backup schedule options NAME`.

**Backups themselves are not.** `create`, `retain`, `delete`, `restore` and `export` act on Capella only:
- Back up before a change: `capellactl cluster backup create NAME`, `capellactl bucket backup create CLUSTER BUCKET`
  (both wait until the backup is done; `--no-wait` returns at once).
- List: `capellactl cluster backup list NAME` (without NAME: every cluster of every project in capella.yaml, or of --project),
  `capellactl bucket backup list CLUSTER [BUCKET]`, `capellactl bucket backup cycle list CLUSTER BUCKET`.
- Restore: `capellactl cluster backup restore NAME BACKUP_ID` replaces all data of the cluster;
  `capellactl bucket backup restore CLUSTER BACKUP_ID [--to-cluster NAME] [--include-data B.S.C]` keeps newer
  documents unless `--force-updates`. Both ask you to type the cluster name (or `--auto-approve`).
- Delete: deleting a bucket backup deletes its whole cycle; the command says how many backups that is.
- Download: `capellactl bucket backup export CLUSTER BACKUP_ID` packages the backup's cycle as a zip and prints a
  download link that is valid for one hour. Treat it like a password.

Free-tier clusters have no backups. Most backup operations need an API key with the **Organization Owner** or
**Project Owner** role; with a Project Manager key, `sync` keeps the schedules capella.yaml already has.

Step by step: docs/backup-restore.md.
