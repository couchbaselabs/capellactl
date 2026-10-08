# capellactl

`capellactl` is a command-line tool that sets up and manages a Couchbase Capella environment from one YAML file: projects, clusters, allowed IP ranges, buckets, scopes, collections and database credentials. It uses the [Capella Management API v4.0](https://docs.couchbase.com/cloud/management-api-reference/index.html).

## What it does

capellactl keeps `capella.yaml`, a description of your environment, in step with Capella: commands change Capella and record the change in the file, and `plan`/`apply` make Capella match the file.

- **Idempotent:** running `apply` again when nothing changed reports `No changes`; safe from CI or cron.
- **Plan first:** `plan` shows every create, update and delete before anything happens.
- **Safe:** nothing is deleted unless you ask; changes Capella cannot make in place (for example a cloud region) are refused, never done by delete and re-create.
- **No hand-editing, no state file:** capellactl writes `capella.yaml` for you; Capella is the source of truth (`capellactl sync` brings in changes made in the Capella UI).

## Install

Requires Python 3.10 or later. Until the package is published, install from the repository:

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e .
source .venv/bin/activate && capellactl --version
```

Standalone executables (no Python needed) are planned in [CAP-045](docs/release-1.0.0/CAP-045-standalone-executables.md).

<!-- downloads:start -->
| Your computer | File (from release 1.0.0) |
|---|---|
| macOS, Apple silicon (M1–M4) | `capellactl-<version>-macos-arm64` |
| macOS, Intel | `capellactl-<version>-macos-x86_64` |
| Linux x86-64 (glibc 2.28+: RHEL/Rocky 8+, Ubuntu 20.04+, Debian 10+) | `capellactl-<version>-linux-x86_64` |
| Linux ARM64 (glibc 2.28+: AWS Graviton, Ampere) | `capellactl-<version>-linux-arm64` |
| Windows 10/11 and Server 2019+, 64-bit | `capellactl-<version>-windows-x86_64.exe` |

Not built yet. Once released, this table is generated from `downloads/` with each file's size, SHA-256 checksum and a download link.
<!-- downloads:end -->

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

For CI, set `CAPELLA_API_KEY` and `CAPELLA_ORG_ID` instead of running `configure`, and pass `--auto-approve`.

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

Global flags: `--config`, `--profile`, `-o text|json`, `--log-level`, `--auto-approve`, `--no-wait`, `--timeout`. `capellactl help topics` lists the guides built into the tool; `capellactl help exit-codes` explains exit codes.

Passwords are never written to `capella.yaml` or printed: give them as `--password-env VAR` or `--password-file PATH` (recorded as `${VAR}`). A password Capella generates is saved once to `.capellactl/credentials/` with owner-only permissions.

## Documentation

| Document | For |
|---|---|
| [Getting started](docs/getting-started.md) | Step-by-step walkthrough with example output, from install to deleting a cluster, and troubleshooting |
| [Cheatsheet](docs/release-1.0.0/cheatsheet.md) | Copy-paste commands and a 15-minute demo script |
| [Example capella.yaml](docs/release-1.0.0/examples/capella.yaml) | Every supported field, annotated |
| [Architecture](docs/release-1.0.0/00-architecture.md) | Design, idempotency rules, test conventions |
| [INDEX.md](docs/release-1.0.0/INDEX.md) | Release plan and user stories |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to build, test and change the project |

Couchbase also publishes an official Terraform provider for Capella; teams already on Terraform may prefer it.

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
| [docs/](docs/) | [Architecture](docs/release-1.0.0/00-architecture.md), user stories (`CAP-NNN-*.md`), [INDEX.md](docs/release-1.0.0/INDEX.md), [API coverage](docs/release-1.0.0/API-COVERAGE.md), [cheatsheet](docs/release-1.0.0/cheatsheet.md), [examples](docs/release-1.0.0/examples/) |

Build, test and documentation conventions: [CONTRIBUTING.md](CONTRIBUTING.md) and the [Makefile](Makefile).

## Licence

capellactl is licensed under the [Apache License 2.0](LICENSE). Copyright 2026 Couchbase, Inc.; see [NOTICE](NOTICE). The open-source packages it depends on, and their licences, are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
