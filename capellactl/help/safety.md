# Safety

- **Nothing is deleted unless you ask**: `delete`, `destroy` or `apply --prune`. Removing something
  from the file does not delete it; `drift` lists it as unmanaged.
- **Deletion protection** (`deletionProtection: true`) blocks deleting the cluster and its buckets,
  scopes and collections, and bucket flush. Turn it off first: `capellactl cluster protect NAME --off`.
- **Blocked changes** stop the whole apply before anything is changed: immutable fields, failed or
  degraded clusters, ambiguous names, unsafe scale-in, turned-off clusters, buckets that need more
  memory than the cluster has free or more replicas than it has data nodes for, collection maxTTL
  changes on Couchbase Server older than 7.6.0.
- **Confirmation**: apply asks before changing anything; destructive changes are listed again.
  `--auto-approve` skips the prompt (CI). Without a terminal, apply refuses unless `--auto-approve`.
- **Bucket deletes** show the item count, memory used and the credentials that lose access, and ask
  you to type the bucket name (`bucket delete`, and each bucket in `apply --prune`).
- **Scope and collection deletes** list the collections whose documents are deleted and the credentials
  that lose access, and ask you to type the name (`scope delete`, `collection delete`, and each one in
  `apply --prune`). The `_default` and `_system` scopes and the `_default` collection are never deleted.
- **Cluster deletes** (`cluster delete`) list the node count, buckets and hibernation schedule that go with
  the cluster, keep snapshot backups unless `--discard-snapshots`, ask you to type the cluster name, and wait
  until the cluster is gone.
- **Allowed CIDRs** that are in Capella but not in the file are listed by `plan` as unmanaged; only
  `apply --prune` deletes them. `0.0.0.0/0` needs `allowAnyIp: true`.
- **No cascade by default**: deleting a project with clusters needs `--cascade`.
- **Partial failure**: apply stops at the first error. Fix it and re-run; finished steps are not repeated.
