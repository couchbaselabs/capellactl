# CAP-043 — One-command build of the distributables (source release)

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P0 | 3 | CAP-001, CAP-044 | In progress |

## User story
As a **maintainer shipping capellactl as source code to every team**, I want one command that builds the source archive, the wheel and their checksums the same way on any machine and in CI, so that releasing is simple and anyone can rebuild, verify and install exactly what we shipped.

## Context & discovery
As built today:
- `make build` runs `pip wheel --no-deps -w dist .` and produces only a wheel. The CI smoke job and the Dockerfile each build the wheel again in their own way.
- There is no source archive (sdist) target, no checksums and no release workflow; versions are edited by hand in `pyproject.toml` (`1.0.0.dev0`).
- `pyproject.toml` declares `Apache-2.0`, but the repository has no `LICENSE` file. Choosing and recording the licence is CAP-044; this story only makes sure the files ship.
- hatchling's default sdist contains every file that is not git-ignored. Today that would include a developer's `capella.yaml` at the repository root, `secrets/` and other local files.

## Implementation details
- `make dist` (and `python scripts/build-dist.py` for machines without make) does the following:
  1. Cleans `dist/`.
  2. Builds `capellactl-<version>.tar.gz` (sdist) and `capellactl-<version>-py3-none-any.whl` with `python -m build`.
  3. Writes `SHA256SUMS`.
  4. Checks both artifacts (contents allowlist and `twine check`).
  5. Prints where they are.
- **What ships:** an explicit `[tool.hatch.build.targets.sdist]` include list covering `capellactl/` (with `schema.json` and `help/*.md`), `tests/`, `docs/`, `scripts/`, `README.md`, `CONTRIBUTING.md`, `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md` (CAP-044), `CHANGELOG.md`, `pyproject.toml`, `Makefile` and `Dockerfile`. Everything else is excluded, so local `capella.yaml`, `*.bak`, `.capellactl/`, `secrets/` and assistant files can never ship.
- **Version:** single-sourced. A release build takes it from the git tag `vX.Y.Z` (hatch-vcs or an equivalent); `capellactl --version`, the artifact names and `CHANGELOG.md` agree. Untagged builds are marked as development versions.
- **Reproducible:** `SOURCE_DATE_EPOCH` is taken from the tagged commit, so two builds of the same tag produce identical archives.
- **Release workflow** (`.github/workflows/release.yml`, on tag push):
  - runs `make check` and `make dist`;
  - installs the sdist and the wheel in clean virtualenvs on Linux, macOS and Windows;
  - attaches the archives and `SHA256SUMS` to the GitHub Release.
- The Dockerfile and the CI smoke job install the wheel built by `make dist` instead of building their own.

## Acceptance criteria & tests

### AC1 — One command builds everything
**Given** a clean checkout and Python 3.10–3.13, **when** `make dist` runs, **then** `dist/` contains exactly the sdist, the wheel and `SHA256SUMS`, and the checksums verify (`sha256sum -c`).

| Test | Location | Verifies |
|---|---|---|
| `test_dist_ac1_make_dist_outputs` | `tests/unit/test_packaging.py` | |

### AC2 — Installs and runs from the source archive
**Given** only the sdist, **when** it is installed with `pip install capellactl-<version>.tar.gz` in a fresh virtualenv, **then** `capellactl --version`, `capellactl help topics` and `capellactl validate` on the example file work (packaged schema and help files are present). The same holds for the wheel and for `pipx install`.

| Test | Location | Verifies |
|---|---|---|
| `test_dist_ac2_install_from_sdist` | `tests/unit/test_packaging.py` | |
| release workflow install matrix | `.github/workflows/release.yml` | Linux, macOS, Windows |

### AC3 — Nothing local or secret ships
**Given** a working tree containing `capella.yaml`, `capella.yaml.bak`, `.capellactl/credentials`, `secrets/pw.txt` and `CLAUDE.md`, **when** `make dist` runs, **then** none of them is in the sdist or the wheel, and the build fails if the archive contains any file outside the allowlist.

| Test | Location | Verifies |
|---|---|---|
| `test_dist_ac3_no_local_files_in_archives` | `tests/unit/test_packaging.py` | |

### AC4 — Licence and notices included
**Given** the built archives, **then** the sdist contains `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md` (all from CAP-044) and `CHANGELOG.md`, the wheel contains `LICENSE` and `NOTICE`, and `twine check` passes.

| Test | Location | Verifies |
|---|---|---|
| `test_dist_ac4_license_files` | `tests/unit/test_packaging.py` | |

### AC5 — One version everywhere
**Given** tag `v1.0.0`, **then** the artifacts are named `capellactl-1.0.0…`, `capellactl --version` prints `1.0.0`, and the build fails if `CHANGELOG.md` has no `1.0.0` entry. An untagged build is a development version (for example `1.0.1.dev3+g1a2b3c4`).

| Test | Location | Verifies |
|---|---|---|
| `test_dist_ac5_version_from_tag` | `tests/unit/test_packaging.py` | |

### AC6 — Reproducible
**Given** the same tag built twice (on different machines or at different times), **then** the sdist and wheel are byte-identical (same `SHA256SUMS`).

| Test | Location | Verifies |
|---|---|---|
| `test_dist_ac6_reproducible_build` | `tests/unit/test_packaging.py` | |

### AC7 — Release on tag
**Given** a pushed tag `vX.Y.Z`, **then** the release workflow runs the checks, builds with `make dist`, runs the install matrix, and publishes the archives and `SHA256SUMS` to the GitHub Release. The workflow fails without publishing if any step fails.

| Test | Location | Verifies |
|---|---|---|
| release workflow dry run on a pre-release tag | `.github/workflows/release.yml` | Manual check, recorded in the story |

### AC8 — One build path
**Given** the Dockerfile and the CI install smoke job, **then** both install the wheel produced by `make dist`; `make build` is removed or calls `make dist`.

| Test | Location | Verifies |
|---|---|---|
| `test_dist_ac8_single_build_path` | `tests/unit/test_packaging.py` | Dockerfile/CI reference `make dist` artifacts |

## Out of scope
- Publishing to PyPI or an internal package index (the archives are ready for it; where to publish is a later decision).
- Standalone single-file executables: CAP-045 (PyInstaller builds per platform in `downloads/`). OS packages (Homebrew, apt, MSI).
- Signing artifacts (Sigstore/GPG).

## Open questions
- ~~Should the sdist include `tests/` and `docs/`?~~ Answered (2026-10-08), as proposed: yes, a complete source release (`tests/`, `docs/`, `scripts/`), so anyone can rebuild and test what was shipped.
- ~~Do we also need a zipapp/shiv single-file build for machines where pip cannot install packages?~~ Answered (2026-10-06): yes, as standalone executables that need no Python, in CAP-045.

## Implementation notes (as built)
- **Still open: AC7.** The release workflow needs one dry run on GitHub: Actions → release → Run workflow (a
  manual run builds, checks and installs on Linux, macOS and Windows, and publishes nothing). Record the run
  here, then set the story to Implemented. `test_dist_ac7_release_workflow` checks the workflow's steps statically.
- Version: `scripts/version.py`, hatchling's `code` version source (no hatch-vcs dependency). A `vX.Y.Z` tag on
  HEAD gives `X.Y.Z`; after it, `X.Y.(Z+1).devN+gSHA`; before the first tag, `1.0.0.devN+gSHA`; a source archive
  reads its own `PKG-INFO`. `capellactl.__version__` comes from the installed package's metadata.
- `scripts/build-dist.py` builds the sdist, then the wheel from the sdist (`python -m build --no-isolation`), so a
  wheel that builds proves the archive is complete. It checks both against an allowlist, plus a list of names that
  never ship anywhere (local `capella.yaml`, `*.bak`, `.capellactl/`, `secrets/`, `.env`, assistant files; the
  documented examples and test fixtures are allowed), runs `twine check --strict`, and writes `SHA256SUMS`.
- hatchling adds `.gitignore` to the sdist (it keeps the same exclusions when the wheel is built from it); it is on
  the allowlist.
- `python -m capellactl` works (new `capellactl/__main__.py`); the release install matrix uses it.
- `CHANGELOG.md` is new, with an `## Unreleased` section; a tagged build fails until it has `## X.Y.Z`.
  CONTRIBUTING.md has the release steps.
- The Dockerfile is now a single stage that installs `dist/capellactl-*.whl`; `make image` runs `make dist` first.
  `make build` calls `make dist`.
- `build` and `twine` were added to the `dev` extra.

### Tests by AC

| AC | Tests (tests/unit/test_packaging.py) |
|---|---|
| AC1 | `test_dist_ac1_make_dist_outputs` |
| AC2 | `test_dist_ac2_install_from_sdist` (sdist and wheel); release workflow install matrix (Linux, macOS, Windows × Python 3.10, 3.13, plus pipx) |
| AC3 | `test_dist_ac3_no_local_files_in_archives`, `test_dist_ac3_archive_outside_allowlist_fails` |
| AC4 | `test_dist_ac4_license_files` |
| AC5 | `test_dist_ac5_version_from_tag` |
| AC6 | `test_dist_ac6_reproducible_build` |
| AC7 | `test_dist_ac7_release_workflow` (static); dry run on GitHub still to do |
| AC8 | `test_dist_ac8_single_build_path` |
