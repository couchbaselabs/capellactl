# CI/CD pipelines

capellactl never waits for input without a terminal, so a pipeline cannot hang on a prompt.

## Approval

- `--auto-approve` (or `--yes`, `-y`), before the command, approves every change that command makes:
  creates, updates, scaling, deletes and `apply --prune`.
- It is the only way to approve. There is no environment variable or profile setting for it, so approval is
  always visible in the pipeline file and its logs, and a variable left set in a shell can never delete data.
- Without a terminal and without the flag, every command that changes Capella or capella.yaml stops with
  exit code 1 and changes nothing: `refusing to <verb> without approval; pass --auto-approve`.
- A question that has a default uses it. A question that needs an answer stops with exit code 3:
  `missing --FLAG (no terminal to ask; pass it on the command line)`.

## Credentials

Set `CAPELLA_API_KEY` and `CAPELLA_ORG_ID` from the pipeline's secret store instead of running `configure`.
See `capellactl help environment`.

## Quiet output

`--quiet` (`-q`) or `CAPELLACTL_QUIET=true` drops progress lines, hints and "previous version kept" notes.
Before a change, only the plan summary line is printed, then the result table (or, with `-o json`, the JSON
document). Errors and blocked changes are always printed in full, and exit codes do not change.

## Installing in a pipeline

Install the wheel attached to the GitHub Release (see the README), or use the container image.

## Gating on changes

`capellactl plan --detailed-exitcode` exits 0 when Capella matches capella.yaml, 2 when there are changes,
3 when the file is invalid and 4 when a change is blocked. `capellactl drift --detailed-exitcode` works the
same way for changes made outside capellactl. See `capellactl help exit-codes`.

## GitHub Actions

```yaml
jobs:
  capella:
    runs-on: ubuntu-latest
    env:
      CAPELLA_API_KEY: ${{ secrets.CAPELLA_API_KEY }}
      CAPELLA_ORG_ID: ${{ secrets.CAPELLA_ORG_ID }}
    steps:
      - uses: actions/checkout@v4
      - run: pip install https://github.com/couchbaselabs/capellactl/releases/download/v1.0.0/capellactl-1.0.0-py3-none-any.whl
      - run: capellactl validate
      - run: capellactl plan --detailed-exitcode || [ $? -eq 2 ]   # 2: changes to apply
      - run: capellactl --auto-approve --quiet apply
        if: github.ref == 'refs/heads/main'
```

## GitLab CI

```yaml
capella:
  image: python:3.12
  variables:
    CAPELLACTL_QUIET: "true"
  script:
    - pip install https://github.com/couchbaselabs/capellactl/releases/download/v1.0.0/capellactl-1.0.0-py3-none-any.whl
    - capellactl validate
    - capellactl --auto-approve apply
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

`CAPELLA_API_KEY` and `CAPELLA_ORG_ID` come from the project's masked CI/CD variables.

A second run of the same `apply` makes no changes and exits 0.
