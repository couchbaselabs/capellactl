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
- Custom clusters from the CLI: several service groups (multi-dimensional scaling) with
  `cluster create --group SERVICES:NODESxCPU/RAM[:DISK]` or the interactive `custom` → `multiple groups` questions;
  `cluster group list|add|remove`; `--single-node`, `--server-version`, `--zone`, `--cmek-id`, `--private-dns` and
  `--disk-auto-expansion`; node sizes Capella offers in `cluster options`, with a warning for any other size. Guide:
  [docs/custom-clusters.md](docs/custom-clusters.md).
- `sync` is the one command for `capella.yaml`: it writes the file when there is none, refreshes it, and adds the
  organization's projects that are missing (`--skip-project` leaves one out). `import` remains as an alias.
- `sync` keeps the buckets and credentials of a cluster that is turned off (or cannot be read) instead of removing them
  from `capella.yaml`.
- Non-interactive (CI/CD) mode: `--auto-approve`/`--yes`/`-y` is the only approval, nothing waits for input without
  a terminal, and `--quiet` keeps pipeline logs short (`capellactl help ci`).
- Secret redaction everywhere, generated passwords saved locally, API Key Token in the OS keychain.
- `make dist`: source archive, wheel and `SHA256SUMS`, reproducible and versioned from the git tag.
