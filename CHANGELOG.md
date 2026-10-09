# Changelog

All notable changes to capellactl. A release build (`make dist` on a `vX.Y.Z` tag) fails unless this file has a
`## X.Y.Z` section, so add one before tagging.

## Unreleased

First release, 1.0.0: declarative management of Couchbase Capella through the Management API v4.0.

- `configure`, `init`, `import`, `sync`, `validate`, `plan`, `apply`, `destroy`, `drift` for a whole environment
  described in `capella.yaml` (one or several projects).
- Projects, clusters (including the free tier), scaling (out, in, up, step scaling with guardrails), power off/on,
  hibernation schedules, deletion protection, allowed CIDRs, buckets, scopes, collections and database credentials,
  each with list/get/create/update/delete commands that record the change in `capella.yaml`.
- `cluster clone`: deploy a copy of a cluster in another region.
- Non-interactive (CI/CD) mode: `--auto-approve`/`--yes`/`-y` is the only approval, nothing waits for input without
  a terminal, and `--quiet` keeps pipeline logs short (`capellactl help ci`).
- Secret redaction everywhere, generated passwords saved locally, API Key Token in the OS keychain.
- `make dist`: source archive, wheel and `SHA256SUMS`, reproducible and versioned from the git tag.
