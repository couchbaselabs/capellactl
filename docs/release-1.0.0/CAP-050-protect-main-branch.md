# CAP-050 — Protect `main`: changes only through a reviewed pull request

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P0 | 3 | CAP-001, CAP-043 | In progress |

## User story
As the **maintainer opening capellactl to the public after release 1.0.0**, I want every change to `main` to arrive through a pull request from a branch that has been reviewed and has passed CI, so that no one, including me or another admin, can push or merge unreviewed code into the branch that releases are tagged from.

## Context & discovery
As built today:
- `couchbaselabs/capellactl` has no branch protection or ruleset on `main`. Anyone with write access can push to it directly, force-push or delete it, and a pull request can be merged with failing or unfinished checks.
- `.github/workflows/ci.yml` already runs on every `pull_request`: one `test` job per OS and Python version (`test (ubuntu-latest, 3.10)` … `test (windows-latest, 3.13)`, six in total). Nothing requires these checks to pass before merging.
- Release tags (`v*`) trigger `.github/workflows/release.yml` (CAP-043), which publishes the GitHub Release. Today anyone with write access can create or move a tag, so a release could be cut from code that was never reviewed.
- The repository has no `CODEOWNERS` file. CONTRIBUTING.md already says changing `scripts/licence-policy.json` "needs the code owner's approval", but nothing enforces that.
- Once the repository is public, pull requests will also come from forks. Workflows on fork PRs run with a read-only token and no secrets (GitHub default), so CI can run on them safely. Whether a first-time contributor's workflow runs at all depends on the repository's "Approval for running fork pull request workflows" setting.
- GitHub has two mechanisms: classic **branch protection** and **repository rulesets**. Rulesets can be exported and imported as JSON, cover tags as well as branches, and let you choose exactly who may bypass them. **Chosen: rulesets.** They are kept in the repository and applied with `gh api`, so the settings are reviewed like code and can be checked for drift.

## Implementation details

### Rulesets kept in the repository
`.github/rulesets/main.json` (target: the default branch):
- `pull_request`: at least 1 approving review; approval by a code owner required; stale approvals dismissed when new commits are pushed; the most recent push must be approved by someone other than its author; every review conversation resolved before merge.
- `required_status_checks`: the six `ci / test (<os>, <python>)` checks, with `strict_required_status_checks_policy: true` (the branch must be up to date with `main` before it can merge).
- `non_fast_forward` (no force-push), `deletion` (`main` cannot be deleted), `required_linear_history` (squash or rebase merges only).
- `bypass_actors`: empty, so the rules apply to admins too (see open questions for a break-glass exception).

`.github/rulesets/release-tags.json` (target: tags matching `v*`): only the maintainers' team may create tags; no one may update or delete them. A published release can't be moved to other code.

### Applying and checking the rulesets
- `scripts/github-rulesets.py apply` creates or updates both rulesets on `couchbaselabs/capellactl` through `gh api repos/{owner}/{repo}/rulesets`. It matches existing rulesets by name and is idempotent: a second run changes nothing.
- `scripts/github-rulesets.py --check` reads the live rulesets and exits non-zero, with a diff, when they differ from the JSON files. The `check` job of `release.yml` runs it, so a release fails if the protection was loosened. It needs a token with `administration:read`, stored as a repository secret.
- `make rulesets` runs `apply`; `make rulesets-check` runs `--check`. Neither is part of `make check`, which must work offline and without credentials.

### Code owners and contributor guidance
- `.github/CODEOWNERS`: `* @couchbaselabs/capellactl-maintainers`. `scripts/licence-policy.json`, `.github/` and `scripts/github-rulesets.py` are listed explicitly, so changes to the protection itself, the CI and the licence policy always need a maintainer's review.
- `.github/pull_request_template.md`: linked story ID, tests run, and a checklist item for the CLAUDE.md/CONTRIBUTING.md regeneration steps (`make index`, `make coverage`).
- CONTRIBUTING.md gets a **How changes reach main** section: branch from `main`, open a pull request, CI must pass and a code owner must approve, squash or rebase merge. Direct pushes are rejected. Contributors outside the organisation fork the repository first.
- Repository settings recorded in the same section, and in `scripts/github-rulesets.py --check` where the API exposes them: merge commits disabled; "Automatically delete head branches" on; fork PR workflows from first-time contributors need approval.

### Release checklist
Add to the 1.0.0 checklist in `scripts/update-story-index.py`: "`main` and `v*` tag rulesets active and `make rulesets-check` green before the repository is made public (CAP-050)".

## Acceptance criteria & tests

### AC1 — Direct pushes to `main` are rejected
**Given** the rulesets are applied, **when** anyone (including a repository admin) pushes a commit directly to `main`, force-pushes it or deletes it, **then** GitHub rejects the push.

| Test | Location | Verifies |
|---|---|---|
| `test_rulesets_ac1_main_blocks_push_force_and_delete` | `tests/unit/scripts/test_github_rulesets.py` | `main.json` has `pull_request`, `non_fast_forward` and `deletion` rules, and empty `bypass_actors` |
| manual release check | — | `git push origin HEAD:main` from an admin account is refused (recorded in the release notes) |

### AC2 — A pull request merges only after review and green CI
**Given** a pull request into `main`, **when** it has no code-owner approval, has unresolved conversations, is behind `main`, or any required check is failing or missing, **then** it can't be merged. New commits pushed after an approval dismiss that approval.

| Test | Location | Verifies |
|---|---|---|
| `test_rulesets_ac2_review_rules` | `tests/unit/scripts/test_github_rulesets.py` | Approval count ≥ 1, code-owner review, stale-review dismissal, last-push approval, conversation resolution, strict status checks |
| `test_rulesets_ac2_required_checks_match_ci_matrix` | `tests/unit/scripts/test_github_rulesets.py` | Required check names are exactly the job names expanded from the `ci.yml` matrix, so adding or renaming an OS/Python entry without updating the ruleset fails `make check` |

### AC3 — Code owners review the sensitive paths
**Given** `.github/CODEOWNERS`, **then** every path has an owner, and `scripts/licence-policy.json`, `.github/` and `scripts/github-rulesets.py` are listed explicitly.

| Test | Location | Verifies |
|---|---|---|
| `test_rulesets_ac3_codeowners_cover_sensitive_paths` | `tests/unit/scripts/test_github_rulesets.py` | |

### AC4 — Release tags can't be moved or deleted
**Given** the `release-tags` ruleset, **then** `v*` tags can only be created by the maintainers' team, and no one can update or delete them.

| Test | Location | Verifies |
|---|---|---|
| `test_rulesets_ac4_release_tags_immutable` | `tests/unit/scripts/test_github_rulesets.py` | |

### AC5 — Applying is idempotent and drift is detected
**Given** the live rulesets match the JSON files, **when** `scripts/github-rulesets.py apply` runs again, **then** it makes no `POST`/`PUT` calls. **When** a live ruleset differs (a rule removed, a bypass actor added), **then** `--check` exits 1 and names the difference, and the release workflow fails.

| Test | Location | Verifies |
|---|---|---|
| `test_rulesets_ac5_apply_idempotent` | `tests/unit/scripts/test_github_rulesets.py` | `gh api` calls stubbed; second run reads only |
| `test_rulesets_ac5_check_reports_drift` | `tests/unit/scripts/test_github_rulesets.py` | Removed rule and added bypass actor both reported |
| release workflow | `.github/workflows/release.yml` | `check` job runs `scripts/github-rulesets.py --check` |

### AC6 — Contributors know how changes reach `main`
**Given** CONTRIBUTING.md, **then** it has a **How changes reach main** section describing the branch → pull request → review → merge flow and the fork flow for external contributors, and the repository has a pull request template.

| Test | Location | Verifies |
|---|---|---|
| `test_rulesets_ac6_contributing_and_pr_template` | `tests/unit/scripts/test_github_rulesets.py` | |

## Out of scope
- Signed commits (`required_signatures`). Can be added later without changing this flow.
- Merge queues. Not needed at the expected pull request volume.
- Protection for branches other than `main` (release branches don't exist yet).
- Organisation-level rulesets and GitHub plan changes.

## Open questions
- ~~**Who reviews the maintainer's own pull requests?**~~ Answered (2026-10-20): the maintainer is a bypass actor in `pull_request` mode only, until a second code owner exists. Their changes still need a pull request and green CI, just no second approval, and each bypass is visible in the audit log. `main.json`'s `bypass_actors` therefore holds that one entry (`bypass_mode: pull_request`), and AC1's test checks exactly that instead of an empty list.
- ~~Is a break-glass bypass wanted for org admins (for example to fix a broken release workflow), and who holds it?~~ Answered (2026-10-21): no. The maintainer's pull-request bypass of the approvals covers a broken release workflow; nothing bypasses CI.
- ~~Does the `couchbaselabs/capellactl-maintainers` team exist, and who is in it?~~ Answered (2026-10-21): no. The maintainer owns the repository but not the `couchbaselabs` organisation, so can't create a team. CODEOWNERS names `@sahnianuj`; the bypass and tag-creation actor is the repository's **admin role** (rulesets accept roles, teams and apps as bypass actors, not individual users). Replace both with a team if one is created.
- ~~Apply the rulesets before the repository becomes public, or as the first step afterwards?~~ Answered (2026-10-21): before, as recommended. If the organisation's plan doesn't allow rulesets on a private repository, `make rulesets` fails with an error from GitHub; apply them as the first step after making it public.

## Implementation notes (as built)
- **Still open:** applying the rulesets to GitHub, then the manual AC1 check. As the repository admin:
  `brew install gh && gh auth login`, `make rulesets`, then `make rulesets-check` (green) and
  `git push origin HEAD:main` (refused). Add the secret `RULESETS_TOKEN` (a fine-grained token for this repository,
  Administration: read-only), which the release workflow needs on a tag. Then set the story to Implemented.
- **Four rulesets instead of two** (`.github/rulesets/`). A ruleset bypass skips every rule in that ruleset, so a
  single `main` ruleset with the maintainer as a bypass actor would also let them merge with failing CI. Split:
  - `main`: no bypass. Pull request required (no approval count; resolved conversations; squash or rebase), the
    six CI checks (strict: up to date with `main`), no force-push, no deletion, linear history.
  - `main-review`: the approvals (1, code owner, latest push approved by someone else, stale approvals
    dismissed, resolved conversations). The admin role bypasses it in `pull_request` mode only.
  - `release-tags`: no one may update or delete a `v*` tag, with no bypass.
  - `release-tags-create`: only the admin role may create a `v*` tag (bypass `always` for creation only).
- Required check names are the job names, `test (<os>, <python>)`, not `ci / test (…)`: rulesets match the check
  run's name. Each is tied to GitHub Actions (`integration_id` 15368), so no other app can report it.
- `scripts/github-rulesets.py` (`make rulesets`, `make rulesets-check`): compares by ruleset name. Fields the files
  leave out are API defaults and are not compared. Rulesets on GitHub that are not in the files count as drift.
  It also applies and checks the repository settings: merge commits off, squash and rebase on, merged branches
  deleted, and a read-only workflow token that may still open pull requests (the CAP-045 downloads PR).
  The fork-PR approval setting for first-time contributors isn't in this API, so CONTRIBUTING lists it as a
  manual setting.
- `release.yml`: the `check` job runs `--check` (report-only on a manual run; a tag fails if `RULESETS_TOKEN` is
  missing or anything drifted). `publish` starts `ci.yml` on the downloads branch with `gh workflow run`, since
  a pull request opened with the workflow token starts no workflow and the required checks would never appear.
  The maintainer merges that pull request through the `main-review` bypass.
- `.github/CODEOWNERS` (`*`, `/.github/`, `/scripts/github-rulesets.py`, `/scripts/licence-policy.json` →
  `@sahnianuj`), `.github/pull_request_template.md`, and CONTRIBUTING.md **How changes reach main** (also: the
  Releasing steps now go through a pull request and tag the merged commit). The release checklist item was
  already in `scripts/update-story-index.py`.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_rulesets_ac1_main_blocks_push_force_and_delete`; manual push check after `make rulesets` (still to do) |
| AC2 | `test_rulesets_ac2_review_rules`, `test_rulesets_ac2_required_checks_match_ci_matrix` |
| AC3 | `test_rulesets_ac3_codeowners_cover_sensitive_paths` |
| AC4 | `test_rulesets_ac4_release_tags_immutable` |
| AC5 | `test_rulesets_ac5_apply_idempotent`, `test_rulesets_ac5_check_reports_drift`, `test_rulesets_ac5_release_workflow_checks_protection` |
| AC6 | `test_rulesets_ac6_contributing_and_pr_template` |
