# CAP-045 — Standalone executables for macOS, Linux and Windows

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P1 | 5 | CAP-043, CAP-044 | Not started |

## User story
As a **customer operator**, I want to download one file for my computer and run it, without installing Python, pip or Docker, so that I can start using capellactl in minutes on a locked-down laptop or a CI runner.

## Context & discovery
As built today:
- capellactl ships as a wheel and source archive (CAP-043) and a container image. Running it needs Python 3.10+ and `pipx`, or Docker. Many customer machines have neither, or do not allow installing packages.
- CAP-043 lists single-file executables as out of scope and asks, as an open question, whether a single-file build is needed. This story answers it.
- There are two ways to make one file from a Python project:
  - **zipapp / shiv / pex** produce a `.pyz` that still needs Python on the customer's machine. Some dependencies contain compiled code (`jsonschema` → `rpds-py`; on Linux `keyring` → `cryptography`), so a `.pyz` would still be built per platform. Rejected.
  - **PyInstaller one-file builds** bundle the Python interpreter, capellactl and its dependencies into one executable per operating system and processor. Nothing else is needed on the customer's machine. **Chosen.** (Nuitka is the alternative if start-up time or size becomes a problem.)
- An executable can only be built on its own platform, so each one is built by its own job in a CI matrix.
- capellactl reads files from inside its package at run time: `config/schema.json`, `config/presets.yaml` and `help/*.md`. It also loads keychain backends that are imported dynamically. The build must include all of them explicitly.

## Implementation details

### The `downloads/` folder
All executables live in one folder at the repository root, named so the platform is obvious:

```
downloads/
├── README.md                                # generated: which file is for which computer, how to run and verify
├── SHA256SUMS                               # checksums of every executable below
├── capellactl-1.0.0-macos-arm64             # macOS 12+, Apple silicon (M1–M4)
├── capellactl-1.0.0-macos-x86_64            # macOS 12+, Intel
├── capellactl-1.0.0-linux-x86_64            # Linux x86-64, glibc 2.28+ (RHEL/Rocky 8+, Ubuntu 20.04+, Debian 10+)
├── capellactl-1.0.0-linux-arm64             # Linux ARM64, glibc 2.28+ (AWS Graviton, Ampere)
└── capellactl-1.0.0-windows-x86_64.exe      # Windows 10/11 and Server 2019+, 64-bit
```

- File names are `capellactl-<version>-<os>-<arch>[.exe]`, with the same `<os>` and `<arch>` words everywhere: file names, the downloads README, the main README and the GitHub Release.
- The folder holds **only the current release**. Earlier releases stay attached to their GitHub Releases, so the repository does not grow by about 150 MB per release.
- The executables are stored with **Git LFS** (`.gitattributes`: `downloads/capellactl-* filter=lfs diff=lfs merge=lfs -text`), so cloning the source does not download them unless asked (`git lfs pull --include downloads/`).

### Build
- `capellactl.spec` (PyInstaller) at the repository root: one-file mode; console app; bundles `capellactl/config/schema.json`, `capellactl/config/presets.yaml`, `capellactl/help/*.md`, `LICENSE`, `NOTICE` and `THIRD_PARTY_NOTICES.md`; declares the keyring backends as hidden imports (`keyring.backends.macOS`, `.Windows`, `.SecretService`, `.fail`).
- `make binary` (and `python scripts/build-binary.py` for machines without make) builds the executable for the machine it runs on, puts it in `downloads/` under the name above, and runs the smoke checks (AC2) on the result.
- `scripts/update-downloads.py` writes `downloads/SHA256SUMS` and `downloads/README.md`, and refreshes the **Download** block in the root `README.md` (between `<!-- downloads:start -->` and `<!-- downloads:end -->`), all from the files in `downloads/`. It works like `update-story-index.py`, and `--check` fails CI when they are stale.
- Release workflow (extends CAP-043's `.github/workflows/release.yml`), on tag `vX.Y.Z`:
  - a build matrix of `macos-14` (arm64), `macos-13` (x86_64), `ubuntu-22.04` building inside a `manylinux_2_28` container (x86_64), `ubuntu-22.04-arm` (arm64) and `windows-2022` (x86_64). Each job runs `make binary` and uploads its executable;
  - a final job collects the five files into `downloads/`, runs `update-downloads.py`, commits `downloads/` and the README block to the release branch, and attaches the executables and `SHA256SUMS` to the GitHub Release next to CAP-043's archives.
- **Signing:** macOS executables are signed with the Developer ID certificate and notarized, so Gatekeeper opens them without the "unidentified developer" block. The Windows `.exe` is Authenticode-signed. Credentials come from CI secrets and never from the repository.

### README
The root `README.md` gets a **Download** section, placed before **Install**. Its generated block is a table:

| Your computer | File | Size | SHA-256 |
|---|---|---|---|
| macOS, Apple silicon (M1–M4) | [capellactl-1.0.0-macos-arm64](downloads/capellactl-1.0.0-macos-arm64) | 28 MB | `ab12…` |
| macOS, Intel | … | | |
| Linux x86-64 (glibc 2.28+) | … | | |
| Linux ARM64 (glibc 2.28+) | … | | |
| Windows 10/11, 64-bit | … | | |

The table is followed by three-line run instructions per OS (`chmod +x`, then run; on Windows, run the `.exe` from PowerShell), how to find your processor (`uname -m`, or *About This Mac*), and how to verify the checksum (`shasum -a 256 -c`, or `Get-FileHash` on Windows).

## Acceptance criteria & tests

### AC1 — One file per platform, built by one command
**Given** a clean checkout on any of the five platforms, **when** `make binary` runs, **then** exactly one executable for that platform appears in `downloads/` with the name `capellactl-<version>-<os>-<arch>[.exe]`. The release workflow produces all five.

| Test | Location | Verifies |
|---|---|---|
| `test_binary_ac1_name_for_platform` | `tests/unit/test_binary.py` | Name from `platform.system()` / `platform.machine()` mapping, including `aarch64`→`arm64`, `AMD64`→`x86_64` |
| release workflow build matrix | `.github/workflows/release.yml` | Five jobs, five files |

### AC2 — Runs with nothing installed
**Given** a clean machine (CI runner image without Python on the PATH, or a `debian:10-slim` / `rockylinux:8` container for Linux), **when** the executable runs, **then** `--version` prints the release version, and `help topics`, `help config clusters.deletionProtection`, `validate` on the example file and `init --non-interactive --dry-run --org-id x --project p --cluster c` all succeed. This proves that the schema, presets and help pages are bundled.

| Test | Location | Verifies |
|---|---|---|
| `test_binary_ac2_smoke` | `tests/binary/test_smoke.py` | Runs against the built file (marker `binary`, run by `make binary` and in the matrix) |

### AC3 — The `downloads/` folder is complete and verifiable
**Given** a release, **then** `downloads/` contains exactly the five executables, `SHA256SUMS` and `README.md`; `shasum -a 256 -c SHA256SUMS` passes; every executable carries the same version; no file from an earlier release remains.

| Test | Location | Verifies |
|---|---|---|
| `test_binary_ac3_downloads_folder_contents` | `tests/unit/test_binary.py` | Allowlist, checksums, single version |

### AC4 — README says which file is for which computer
**Given** the files in `downloads/`, **then** the root README's **Download** section and `downloads/README.md` list each one with its OS, processor, minimum OS version, size, SHA-256 and a link. Each section also explains how to run and verify the file on macOS, Linux and Windows. `scripts/update-downloads.py --check` fails CI when the README lists a file that does not exist, misses one that does, or shows a stale checksum.

| Test | Location | Verifies |
|---|---|---|
| `test_binary_ac4_readme_download_table` | `tests/unit/test_binary.py` | Generated table matches the folder; `--check` detects each kind of drift |

### AC5 — Same behaviour as the installed tool
**Given** the executable, **then** the OS keychain works (`configure` stores and reads the API Key Token on macOS Keychain, Windows Credential Manager and Linux Secret Service), and so do exit codes and secret redaction. A missing keychain falls back to the same message as the pip-installed tool.

| Test | Location | Verifies |
|---|---|---|
| `test_binary_ac5_keychain_and_exit_codes` | `tests/binary/test_smoke.py` | Store and read a dummy token, then remove it; `validate` on an invalid file exits 3 |

### AC6 — Opens without security warnings
**Given** a downloaded macOS executable, **then** `spctl --assess --type execute` accepts it (signed and notarized). **Given** the Windows `.exe`, **then** `Get-AuthenticodeSignature` reports `Valid`. On a release tag, the release fails if signing credentials are missing.

| Test | Location | Verifies |
|---|---|---|
| release workflow signing steps | `.github/workflows/release.yml` | `spctl`, `Get-AuthenticodeSignature` |

### AC7 — Nothing local or secret is bundled
**Given** a working tree containing `capella.yaml`, `.capellactl/credentials`, `secrets/`, `.env` and assistant files, **when** the executable is built, **then** its bundled file list (`pyi-archive_viewer`) contains only the package, its dependencies and the allowed data and licence files. `LICENSE`, `NOTICE` and `THIRD_PARTY_NOTICES.md` are inside it and next to it in `downloads/`.

| Test | Location | Verifies |
|---|---|---|
| `test_binary_ac7_bundle_allowlist` | `tests/binary/test_smoke.py` | |

### AC8 — Reasonable size and start-up
**Given** any executable, **then** it is under 50 MB, and `--version` returns in under 2 seconds on the CI runner (one-file builds unpack themselves on every start).

| Test | Location | Verifies |
|---|---|---|
| `test_binary_ac8_size_and_startup` | `tests/binary/test_smoke.py` | |

## Out of scope
- OS packages and package managers (Homebrew tap, `apt`/`rpm`, winget, MSI installer) and auto-update.
- Linux builds for musl (Alpine) and 32-bit or other processors; Alpine users use the container image.
- Publishing to PyPI (CAP-043 decision).

## Open questions
- Is Git LFS available on the Git host the code is shared from, and do customers receive the repository or only the GitHub Release? If LFS is not available, `downloads/` keeps only `README.md` and `SHA256SUMS` in Git, and its links point to the GitHub Release assets instead.
- Who owns the Apple Developer ID and Windows code-signing certificates, and are they available to CI?
- Is the Linux minimum glibc 2.28 acceptable (it rules out RHEL/CentOS 7)?
