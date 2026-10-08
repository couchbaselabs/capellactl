# The config file (capella.yaml)

One file describes your organization: every project (`projects:`), its clusters, and for each cluster
its scaling, hibernation schedule, allowed IPs, buckets, scopes, collections and credentials.
Field names are the same as in the Capella Management API request bodies. Files in the older
single-project form (`project:` + `clusters:`) still work and are converted on the next write.
capellactl writes and maintains this file (import, project create, cluster create/update/scale, sync).

**Where it is found** (first match wins): `--config PATH`, `CAPELLACTL_CONFIG`, the profile's
`configFile`, `./capella.yaml`, `./capella.yml`. Having both `.yaml` and `.yml` is an error.

**Secrets and variables**
- `${VAR}` is replaced by an environment variable, `${file:./path}` by a file's content.
- Passwords must be `${VAR}` or `${file:...}`; a literal password is rejected.
- The API key never goes in this file.

**Defaults** applied before comparing: bucket `type: couchbase`, `replicas: 1`,
`durabilityLevel: none`, `timeToLiveInSeconds: 0`, `flushEnabled: false`,
`bucketConflictResolution: seqno`; cluster `configurationType: multiNode`.

**Checks** `capellactl validate` runs offline: schema and allowed values, node limits, disk type per
cloud provider, unique names, and that credentials only reference buckets, scopes and collections
defined in the file (or marked `external: true`).

Look up any field: `capellactl help config clusters.buckets.storageBackend`.
