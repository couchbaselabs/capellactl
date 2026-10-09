# capellactl or the Couchbase Capella Terraform provider?

Both manage Capella as code through the same Management API v4.0. They suit different teams. Use one tool per
project: if both manage the same project, each sees the other's changes as drift.

## Prefer the Terraform provider when

- **Your organization already runs Terraform** (or OpenTofu) for its cloud accounts, with remote state, plan
  reviews and policy checks (Sentinel, OPA). Capella then fits the workflow your team already knows.
- **Capella is one part of a larger stack.** One plan can create the VPC, the Capella cluster, the network
  peering or private endpoint, DNS records and the application that connects to it, with dependencies between
  them.
- **You need Capella features that capellactl 1.0 does not manage**, such as App Services, backups and restores,
  network peering, private endpoints, audit logs or alert integrations. The provider covers more of the API;
  `docs/release-1.0.0/API-COVERAGE.md` lists what capellactl covers today.
- **You need shared state and locking** for many engineers changing the same environment at once.

## Prefer capellactl when

- **You want one small command with no state file.** capellactl compares `capella.yaml` with Capella on every
  run, so there is no state to store, lock or repair, and nothing goes wrong when someone changes a setting in the
  Capella UI: `capellactl drift` reports it and `capellactl sync` brings it into the file.
- **You start from an existing environment.** `capellactl import` writes `capella.yaml` from what already runs in
  Capella, and `plan` then reports no changes.
- **Day-2 operations are the main job**: scaling with capacity checks before scale-in, step scaling from alerts
  (`cluster scale --step +1 --max 6`), powering clusters off and on, pausing a hibernation schedule, rotating
  database passwords, or cloning a cluster into another region. Each is one command that also records the change.
- **People without Terraform experience** run the environment: commands ask for what they need, show the plan and
  ask once, and `capellactl help` explains every field and concept offline.

## Moving between them

- From capellactl to Terraform: `capellactl import --full` writes every setting of each cluster, which is a useful
  checklist when writing the Terraform configuration. Import the existing resources into Terraform state with
  `terraform import`, then stop running `capellactl apply` for that project.
- From Terraform to capellactl: run `capellactl import --project NAME`, check that `capellactl plan` reports no
  changes, then remove the resources from Terraform state (`terraform state rm`) so that `terraform destroy` can
  never delete them.
