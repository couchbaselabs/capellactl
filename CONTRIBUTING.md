# Contributing to capellactl

## Progress must always be visible

`docs/release-<version>/INDEX.md` is generated from the header table of each story file
(`docs/release-<version>/CAP-NNN-*.md`). It must reflect reality
at every point, not only at the end of a release.

- When work **starts** on a story, set its **Status** to `In progress`.
- When every AC of a story has a passing test tagged `@pytest.mark.story("CAP-NNN", "ACn")`, set it to `Implemented`.
- A story that is dropped is set to `Descoped` (keep the file and ID; say why in the file).
- After **any** status, points, priority, title or dependency change, regenerate in the same change:
  `python3 scripts/update-story-index.py docs/release-1.0.0` (or `make index`).
- In the same change, regenerate the API coverage reports: `python3 scripts/update-api-coverage.py` (or
  `make coverage`). `docs/release-1.0.0/API-COVERAGE.md` derives every command's and operation's status from the
  story statuses, so a story that becomes Implemented updates it.
- Never edit INDEX.md or the API coverage reports by hand. CI runs
  `python3 scripts/update-story-index.py --check docs/release-1.0.0` and `python3 scripts/update-api-coverage.py --check`
  and fails when any of them is stale.

## API coverage

- Every Management API operation is mapped in `scripts/update-api-coverage.py`, either to the capellactl command(s)
  that call it with their stories, or to a proposed command for a later release. App Services are reported in
  `docs/release-2.0.0/API-COVERAGE-APP-SERVICES.md`; AI operations are out of scope.
- When a story adds a command or starts calling an endpoint, update its entry in the command dictionary (`cmd(...)`)
  or operation map (`op(...)`). If a needed command has no story, write the story first (next free `CAP-NNN`,
  added to a phase in `scripts/update-story-index.py`).
- The fake Capella's responses are checked against the documented responses of every endpoint capellactl calls
  (`docs/api/management-api-v4.0-responses.json`, CAP-004 AC6). When the spec changes or a story calls a new
  endpoint, refresh it with `python3 scripts/update-api-responses.py` (needs network) and fix the fake until
  `tests/unit/fakes/test_fake_parity.py` passes. No test ever calls a real Capella organization.
- The spec is read from the offline snapshot `docs/api/management-api-v4.0-operations.json`. Refresh it with
  `python3 scripts/update-api-coverage.py --refresh-spec` (needs network). The script fails on any new operation
  that is not mapped yet.

## Stories and tests

- Every story AC has at least one test named `test_<subject>_ac<n>_<behaviour>` and tagged with the
  story marker (docs/release-1.0.0/00-architecture.md §12.2). `scripts/check-ac-coverage.py` fails CI
  when an `Implemented` story has an untested AC and lists the open ACs of `In progress` stories.
- Every resource story keeps an idempotency AC: a second run makes zero `POST`/`PUT`/`DELETE` calls.
- Endpoints, fields and enums come from the Capella Management API v4.0 OpenAPI spec, never from memory.
- When a story adds or changes user-facing behaviour, update the step-by-step guide `docs/getting-started.md`
  (`tests/scenario/test_readme_walkthrough.py` runs its steps). Keep `README.md` short: overview, install,
  quick start, links.
- When a story changes a day-2 task, update `docs/runbook.md` (its commands are parsed in CI). When it changes
  `capellactl/config/schema.json`, run `make docs`: `docs/reference.md` is generated from the schema and CI fails
  when it is stale.
- When a story is finished, add an **Implementation notes (as built)** section: deviations from the
  original text, and the tests for each AC.

## How changes reach main

`main` is protected by GitHub rulesets kept in `.github/rulesets/` (CAP-050). Direct pushes, force-pushes and
deleting `main` are rejected for everyone, admins included.

1. Branch from `main`, commit, and push the branch. Contributors outside the organisation fork the repository
   and push to their fork.
2. Open a pull request into `main` and fill in the template (story, tests, checklist).
3. It can merge only when the six `test (<os>, <python>)` CI checks pass on a branch that is up to date with
   `main`, every review conversation is resolved, and a code owner (`.github/CODEOWNERS`) has approved the latest
   push. New commits dismiss an earlier approval.
4. Merge with **squash** or **rebase**; merge commits are disabled and the merged branch is deleted.

While there is one maintainer, they merge their own pull requests with the admin bypass of the `main-review`
ruleset (no second approval; each bypass is in the audit log). The `main` ruleset has no bypass, so CI must pass
for them too. Pull requests from first-time contributors' forks need a maintainer's approval before their
workflows run (Settings → Actions → General); fork workflows never receive secrets.

Release tags `v*` can be created only by the repository admin role, and nobody can move or delete one: a broken
release gets a new version, not a re-tag.

The protection is code: change the JSON in `.github/rulesets/` (or `SETTINGS` in `scripts/github-rulesets.py`)
in a pull request, then run `make rulesets` (repository admin, with `gh auth login`). `make rulesets-check`
reports drift, and a release tag fails when GitHub differs from the files (secret `RULESETS_TOKEN`: a
fine-grained token for this repository with Administration read-only).

## Dependencies and licences

capellactl is licensed under Apache-2.0 (`LICENSE`, copyright in `NOTICE`); source files carry no licence
header. When you add, remove or upgrade a runtime dependency, run `make notices` (needs network) and commit
the updated `THIRD_PARTY_NOTICES.md`. CI fails when the file is stale or a dependency's licence is not in
`scripts/licence-policy.json`; changing that list needs the code owner's approval.

## Commands

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
make check        # lint, types, tests, AC coverage, INDEX and API coverage checks
make index        # regenerate INDEX.md
make coverage     # regenerate the API coverage reports (docs/release-*/API-COVERAGE*.md)
make notices      # regenerate THIRD_PARTY_NOTICES.md after a dependency change
make docs         # regenerate docs/reference.md after a schema change
make dist         # source archive, wheel and SHA256SUMS in dist/ (version from the git tag)
make image        # build the container image
make rulesets     # apply .github/rulesets to GitHub (repository admin); make rulesets-check reports drift
```

## Releasing

1. Rename `## Unreleased` in `CHANGELOG.md` to `## X.Y.Z — date` in a pull request, merge it, and tag the
   merged commit on `main` `vX.Y.Z`. The version comes only from the tag (`scripts/version.py`); never edit it in
   a file. Tags can't be moved or deleted (CAP-050).
2. Push the tag. `.github/workflows/release.yml` runs the checks, builds with `make dist`, installs the
   archives on Linux, macOS and Windows, and attaches them with `SHA256SUMS` to the GitHub Release.
   A manual run of the workflow (Run workflow) is a dry run that publishes nothing.
3. Builds between releases are development versions of the next patch release (`1.0.1.devN+gSHA` after
   `v1.0.0`). `NEXT_RELEASE` in `scripts/version.py` is used only before the first release tag exists.
