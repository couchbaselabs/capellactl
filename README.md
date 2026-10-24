# capellactl

`capellactl` is a command-line tool for Couchbase Capella. It creates and manages projects, clusters, buckets, scopes,
collections, database credentials and allowed IP ranges with short, readable commands, and keeps a record of your
whole environment in one file, `capella.yaml`.

## Why capellactl?

Everything in Capella can be automated through the [Capella Management API v4.0](https://docs.couchbase.com/cloud/management-api-reference/index.html),
and capellactl is built on it. But calling the API directly is slow work: you look up URL paths, copy organization,
project and cluster IDs between calls, write JSON bodies, poll until a cluster is ready, and read through nested
responses. Adding one bucket looks like this:

```bash
curl -X POST "https://cloudapi.cloud.couchbase.com/v4/organizations/$ORG_ID/projects/$PROJECT_ID/clusters/$CLUSTER_ID/buckets" \
  -H "Authorization: Bearer $CAPELLA_API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "orders", "type": "couchbase", "storageBackend": "magma", "memoryAllocationInMb": 1024}'
```

With capellactl you use names instead of IDs, and it asks before changing anything:

```bash
capellactl bucket create dev-01 orders --memory 1024 --storage-backend magma
```

## What you get

- **Commands that read like the task.** `cluster create`, `cluster scale`, `bucket create`, `credential create`,
  `cidr create`: no URLs, IDs or JSON. Leave out an option and capellactl asks for it, with a sensible default.
- **A look before every change.** Each command shows its plan (what will be created, changed or deleted) and asks
  `[y/N]`. Deleting anything that holds data asks you to type its name.
- **Waits for you.** Cluster deployments, scaling and power changes wait until the cluster is healthy, with progress
  on screen, and print the connection string when it is ready.
- **Your environment in one file.** Every command records its change in `capella.yaml`, which capellactl writes for
  you. Keep it in Git to see who changed what; `capellactl apply` rebuilds the whole environment from it, and
  `capellactl sync` brings in changes made in the Capella UI. There is no separate state file: Capella is the source
  of truth.
- **Safe by default.** Nothing is deleted unless you ask. Changes Capella cannot make in place, such as moving a
  cluster to another region, are refused instead of done by delete and re-create. Scaling in is checked against
  bucket memory and replicas first, and deletion protection blocks every way of deleting a cluster.
- **Secure credentials.** The API key is stored in your OS keychain. Passwords are read from environment variables or
  files, never written to `capella.yaml` or printed.
- **Ready for scripts and CI/CD.** Running `apply` again when nothing changed reports `No changes`. Every question
  has an option, `--auto-approve` replaces the prompts, `-o json` gives machine-readable output, and exit codes tell a
  pipeline what happened (`capellactl help ci`).
- **Saves money.** Turn clusters off and on, set an office-hours hibernation schedule, or scale one node at a time
  within limits.

capellactl 1.0 covers the operations listed in [API coverage](docs/release-1.0.0/API-COVERAGE.md). For anything
else, use the Capella UI or the Management API directly.

## Install

capellactl has not had its first release yet, so install it from source. It takes a few minutes and needs
[Git](https://git-scm.com/) and Python 3.10–3.13.

**1. Check your Python version.** On many Macs, `python3` is older than 3.10:

```bash
python3 --version                  # 3.10, 3.11, 3.12 or 3.13 is fine
python3.12 --version               # if python3 is older, try a specific version
```

If you have no suitable version, install one: `brew install python@3.12` on macOS, or from
[python.org](https://www.python.org/downloads/). Ubuntu 22.04 and later already include a suitable `python3`.

**2. Install capellactl.** Replace `python3.12` with the command that printed a suitable version:

```bash
git clone https://github.com/couchbaselabs/capellactl.git && cd capellactl
python3.12 -m venv .venv
.venv/bin/pip install -e .
source .venv/bin/activate          # puts capellactl on your PATH; run again in each new terminal
capellactl --version
```
```
capellactl 1.0.0.devN+g… (Management API v4.0)
Licensed under Apache-2.0 · Copyright 2026 Couchbase, Inc.
```

On Windows, activate with `.venv\Scripts\activate` instead. To update later, run `git pull` in the `capellactl`
folder; the environment picks up the new code. Then continue with [Quick start](#quick-start), or the step-by-step
[getting started guide](docs/getting-started.md).

### After the first release (1.0.0)

These are not available yet. From 1.0.0 on, each [GitHub Release](https://github.com/couchbaselabs/capellactl/releases)
will offer two more ways to install:

- **A standalone executable**, one file per platform, with nothing else to install (no Python, pip or Docker):

<!-- downloads:start -->
**Not released yet**: these files are attached to each [GitHub Release](https://github.com/couchbaselabs/capellactl/releases) from 1.0.0 on. Until then, install from source.

| Your computer | File | Size | SHA-256 |
|---|---|---|---|
| macOS 12+, Apple silicon (M1–M4) | `capellactl-<version>-macos-arm64` | | |
| macOS 12+, Intel | `capellactl-<version>-macos-x86_64` | | |
| Linux x86-64, glibc 2.28+ (RHEL/Rocky 8+, Ubuntu 20.04+, Debian 10+) | `capellactl-<version>-linux-x86_64` | | |
| Linux ARM64, glibc 2.28+ (AWS Graviton, Ampere) | `capellactl-<version>-linux-arm64` | | |
| Windows 10/11 and Server 2019+, 64-bit | `capellactl-<version>-windows-x86_64.exe` | | |

How to pick, verify and run the right file: [downloads/README.md](downloads/README.md).
<!-- downloads:end -->

- **A Python wheel**, installed with `pipx install ./capellactl-1.0.0-py3-none-any.whl`.

Building these files (`make dist`) and the development setup are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Quick start

You need a Capella API key (Organization settings → API Keys, with this machine's IP allowed); copy the **API Key Token**.

```bash
capellactl configure                       # saves the token in your OS keychain, writes capella.yaml from Capella
capellactl plan                            # "No changes" for what was discovered
capellactl cluster create nova-dev-02      # asks a few questions, deploys, waits until healthy
capellactl bucket create nova-dev-02 orders --memory 1024
export ORDERS_APP_PW='Orders-Passw0rd-2026!'
capellactl credential create nova-dev-02 orders_app --privileges read+write --bucket orders --password-env ORDERS_APP_PW
capellactl sync                            # pick up changes made in the Capella UI
```

For CI, set `CAPELLA_API_KEY` and `CAPELLA_ORG_ID` instead of running `configure`, and pass `--auto-approve` (or `-y`); `--quiet` keeps pipeline logs short. `capellactl help ci` has GitHub Actions and GitLab CI examples.

## Commands

```
capellactl help | completion | configure | init | import | sync
capellactl validate | plan | apply | drift | destroy
capellactl project    list | get | create | update | delete
capellactl cluster    options | list | get | create | update | scale | delete | protect | power
capellactl cluster schedule show | set | apply | pause | resume | delete
capellactl cidr       list | create | delete
capellactl bucket     list | get | create | update | delete
capellactl scope      list | create | delete
capellactl collection list | create | update | delete
capellactl credential list | get | create | update [--rotate-password] | delete
```

Global flags: `--config`, `--profile`, `-o text|json`, `--log-level`, `--auto-approve` (`--yes`, `-y`), `--quiet` (`-q`), `--no-wait`, `--timeout`. `capellactl help topics` lists the guides built into the tool; `capellactl help exit-codes` explains exit codes.

Passwords are never written to `capella.yaml` or printed: give them as `--password-env VAR` or `--password-file PATH` (recorded as `${VAR}`). A password Capella generates is saved once to `.capellactl/credentials/` with owner-only permissions.

## Documentation

| Document | For |
|---|---|
| [Getting started](docs/getting-started.md) | Step-by-step walkthrough with example output, from install to deleting a cluster, and troubleshooting |
| [Custom clusters and service groups](docs/custom-clusters.md) | Any size and service layout: several service groups (MDS) with `--group`, adding and removing groups, single-node and advanced options |
| [Runbook](docs/runbook.md) | Day-2 tasks with the exact command and expected output, a copy-paste reference of every command, and a 20-minute demo script |
| [capella.yaml reference](docs/reference.md) | Every field: type, default, whether it can change, API mapping (generated from the schema) |
| [Examples](docs/release-1.0.0/examples/) | [Annotated reference](docs/release-1.0.0/examples/capella.yaml), [single-node dev](docs/release-1.0.0/examples/single-node-dev.yaml), [GCP production](docs/release-1.0.0/examples/gcp-prod.yaml), [Azure production](docs/release-1.0.0/examples/azure-prod.yaml), [minimal](docs/release-1.0.0/examples/minimal-cluster.yaml) |
| [Migrating from the scale script](docs/migrating-from-scale-script.md) | `scale_capella_cluster.sh` → capellactl |
| [Architecture](docs/release-1.0.0/00-architecture.md) | Design, idempotency rules, test conventions |
| [Release README](docs/release-1.0.0/README.md) | Release plan and user stories |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to build, test and change the project |

Couchbase also publishes an official Terraform provider for Capella; [capellactl or Terraform?](docs/terraform.md) explains when to prefer it.

## Project structure

| Path | Contents |
|---|---|
| [capellactl/cli/](capellactl/cli/) | Commands (click), one module per command group; [main.py](capellactl/cli/main.py) is the root |
| [capellactl/api/](capellactl/api/) | Management API v4.0 client: auth, retries, pagination, one function per endpoint, typed errors |
| [capellactl/config/](capellactl/config/) | `capella.yaml` schema, loading, validation rules, comment-preserving edits, profiles and settings |
| [capellactl/resources/](capellactl/resources/) | One reconciler per resource kind (project, cluster, bucket, scope, credential, CIDR) |
| [capellactl/engine/](capellactl/engine/) | Planner, executor and waiter for long cluster operations |
| [capellactl/importer/](capellactl/importer/), [output/](capellactl/output/), [help/](capellactl/help/) | `import`/`sync` writer; rendering, redaction and passwords; `capellactl help` pages |
| [tests/](tests/) | `unit/`, `contract/` (mocked HTTP), `scenario/` (CLI against [the fake Capella](tests/fakes/capella.py)), `integration/` (real Capella) |
| [scripts/](scripts/) | Generators and CI checks: story index, API coverage, AC coverage, third-party notices |
| [docs/](docs/) | [Architecture](docs/release-1.0.0/00-architecture.md), user stories (`CAP-NNN-*.md`), [release plan](docs/release-1.0.0/README.md), [API coverage](docs/release-1.0.0/API-COVERAGE.md), [runbook](docs/runbook.md), [examples](docs/release-1.0.0/examples/) |

Build, test and documentation conventions: [CONTRIBUTING.md](CONTRIBUTING.md) and the [Makefile](Makefile).

## Licence

capellactl is licensed under the [Apache License 2.0](LICENSE). Copyright 2026 Couchbase, Inc.; see [NOTICE](NOTICE). The open-source packages it depends on, and their licences, are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
