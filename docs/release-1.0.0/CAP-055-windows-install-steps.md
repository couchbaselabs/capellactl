# CAP-055 — Install and run capellactl on Windows: step-by-step PowerShell table in the README

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E9 Lifecycle & release | P0 | 3 | CAP-033, CAP-045 | In progress |

## User story
As a **customer operator on a Windows laptop**, I want the README's Install section to give me the exact PowerShell
command for each step, with what I should see and what to do when it fails, so that I can install capellactl and
run the quick start without translating macOS/Linux commands myself.

## Context & discovery
- Found 2026-10-28 with a client: they could not get from the README to a working `capellactl --version` on Windows.
  The Install section is written for macOS/Linux. Windows gets one sentence ("activate with
  `.venv\Scripts\activate` instead"), and nothing after Install mentions Windows at all.
- Windows is supported. CI runs the test suite on `windows-latest`, CAP-045 ships a Windows `.exe`, and the keychain,
  profile folder and console output already have Windows code paths. The code works on Windows; the docs do not
  explain how to use it there.
- The release checklist's "time to first environment under 60 minutes" check (CAP-033 AC5) is run on a Mac only.
  On Windows it would fail today. That makes this story P0.

### Where a Windows user needs help, step by step
Each step of the README and the getting-started guide, run as written in **Windows PowerShell 5.1**, which is the
default shell on Windows 10/11 and Server:

| Step | As written today | What happens on Windows | Help needed? |
|---|---|---|---|
| Install Python | "`brew install python@3.12`, or from python.org" | python.org's main download button gives the newest Python, 3.14 or later. `pyproject.toml` allows only `>=3.10,<3.14`, so pip later fails with `requires a different Python`, which does not say what to do. If "Add python.exe to PATH" was not ticked, no `python` command exists | **Yes**: pin 3.12 (`winget install --id Python.Python.3.12 -e`) and use the `py` launcher |
| Check Python | `python3 --version` | `python3` and `python` open the **Microsoft Store** (App execution aliases), or print nothing | **Yes**: `py -3.12 --version` |
| Install Git | link to git-scm.com | Usually missing on customer laptops | **Yes**: `winget install --id Git.Git -e`, then open a new PowerShell window |
| Clone | `git clone … && cd capellactl` | Windows PowerShell 5.1 rejects `&&` (`The token '&&' is not a valid statement separator`) | **Yes**: two lines |
| Create the environment | `python3.12 -m venv .venv` | `python3.12` does not exist on Windows | **Yes**: `py -3.12 -m venv .venv` |
| Install | `.venv/bin/pip install -e .` | Windows has no `.venv/bin`; the folder is `.venv\Scripts` | **Yes**: `.venv\Scripts\python -m pip install -e .` |
| Activate | `source .venv/bin/activate` (Windows: `.venv\Scripts\activate`) | `source` does not exist. `Activate.ps1` is blocked by the default execution policy (`running scripts is disabled on this system`). On a managed laptop, group policy may block it permanently | **Yes**: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or skip activation and run `.venv\Scripts\capellactl.exe` |
| Folder for the environment | `mkdir ~/capella-env && cd ~/capella-env` | `&&` again | **Yes**: `mkdir ~\capella-env; cd ~\capella-env` |
| Find the public IP for the API key | `curl -s https://checkip.amazonaws.com` | In 5.1, `curl` is an alias for `Invoke-WebRequest`, and `-s` is ambiguous, so the command fails | **Yes**: `curl.exe -s https://checkip.amazonaws.com` |
| `configure` (paste the token) | hidden prompt, or `pbpaste \| capellactl configure --api-key-stdin` | Pasting into a hidden prompt shows nothing, so users think it failed. `pbpaste` is macOS only. PowerShell pipes text to programs with a trailing CRLF | **Yes**: right-click or Ctrl+V pastes even though nothing shows; `Get-Clipboard \| capellactl configure --api-key-stdin`. The CRLF must be stripped (AC4) |
| Passwords | `export ORDERS_APP_PW='…'` | `export` does not exist | **Yes**: `$env:ORDERS_APP_PW = '…'` (`set` in cmd.exe) |
| Long commands | lines ending in `\` (getting-started, runbook) | In PowerShell, `\` does not continue a line, so the rest of the command is lost | **Yes**: a trailing backtick `` ` ``, or one line |
| CI | `capellactl plan --detailed-exitcode \|\| [ $? -eq 2 ]` (`help ci`) | bash only | **Yes**, one row: `$LASTEXITCODE` |
| Standalone `.exe` (after 1.0.0) | `downloads/README.md`: hash, `Unblock-File`, run `.\capellactl-…exe` | The checksum and unblock steps are covered. Nothing explains how to type `capellactl` from any folder, so every command in the docs fails unless the user keeps the long file name and `.\` | **Yes**: rename it to `capellactl.exe` and add its folder to the user PATH |
| Keychain | `configure` stores the token in the OS keychain | Windows Credential Manager, through keyring (CAP-045 AC5 tests it on Windows) | No; say where the token is stored |
| Profiles, credentials folder | `profiles.yaml`, `.capellactl/credentials/` | Profiles are in `%APPDATA%\capellactl`; the credentials folder is under the user's profile | No; say where they are |
| Output characters (✓, →, box lines) | — | `main.py` switches stdout to UTF-8 | No |
| Shell completion | `capellactl completion bash\|zsh\|fish` | No PowerShell completion (Click has none) | No; say it is not available |
| `capellactl` commands themselves | `--password-env`, `--password-file`, `-o json`, exit codes | Work the same | No |

So help is needed in three places:
1. **Install**: every step from Python to `capellactl --version`. This is where the client got stuck, and it gets
   the table the README asks for.
2. **The handful of shell differences** after install: env vars, line continuation, clipboard, IP check, `&&`, exit
   codes in CI. One translation table covers every command in the docs, so the docs do not need a Windows copy.
3. **The `.exe` on PATH**, for 1.0.0 and later.

## Implementation details

### README: Install → "On Windows (PowerShell)"
A subsection of **Install**, after the macOS/Linux steps. The macOS/Linux steps stay as they are, apart from saying
they are for macOS and Linux. The table sits between `<!-- windows-install:start -->` and
`<!-- windows-install:end -->` so tests can find it. The **Run in PowerShell** column holds exactly the commands to
type, one backticked command per line:

| Step | Run in PowerShell | You should see / if it fails |
|---|---|---|
| 1. Install Git and Python 3.12 | `winget install --id Git.Git -e`<br>`winget install --id Python.Python.3.12 -e` | Then **close and reopen PowerShell**. No `winget`: install Git from git-scm.com and Python **3.12** from python.org (not the newest version: capellactl needs 3.10–3.13), and tick *Add python.exe to PATH* |
| 2. Check Python | `py -3.12 --version` | `Python 3.12.x`. If `python` opens the Microsoft Store, ignore it and use `py` |
| 3. Download capellactl | `git clone https://github.com/couchbaselabs/capellactl.git`<br>`cd capellactl` | Run these as two commands: Windows PowerShell does not accept `&&` |
| 4. Create its environment | `py -3.12 -m venv .venv` | A `.venv` folder |
| 5. Install it | `.venv\Scripts\python -m pip install -e .` | `Successfully installed … capellactl-…`. `requires a different Python`: step 4 used a Python newer than 3.13 |
| 6. Allow activation (once per user) | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` | Answer `Y`. If your company blocks this, skip steps 6–7 and type `.venv\Scripts\capellactl.exe` wherever the docs say `capellactl` |
| 7. Activate (in each new window) | `.venv\Scripts\Activate.ps1` | The prompt starts with `(.venv)`. In cmd.exe: `.venv\Scripts\activate.bat` |
| 8. Check | `capellactl --version` | `capellactl 1.0.0.devN+g… (Management API v4.0)` |
| 9. Make a folder for your environment | `mkdir ~\capella-env`<br>`cd ~\capella-env` | capellactl writes `capella.yaml` here |

Followed by one line on where things are kept (the API Key Token in **Windows Credential Manager** under
`capellactl`, profiles in `%APPDATA%\capellactl`), and a link to the translation table below.

### getting-started: "Using the commands in PowerShell"
A short table in `docs/getting-started.md` under **Before you start**, linked from the README and from the top of
`docs/runbook.md`. It does not duplicate any command:

| In the docs (macOS/Linux) | In PowerShell |
|---|---|
| `export ORDERS_APP_PASSWORD='…'` | `$env:ORDERS_APP_PASSWORD = '…'` |
| a line ending in `\` | end the line with a backtick `` ` `` instead, or join the lines |
| `a && b` | `a; b` (Windows PowerShell 5.1) |
| `curl -s https://checkip.amazonaws.com` | `curl.exe -s https://checkip.amazonaws.com` |
| `pbpaste \| capellactl configure --api-key-stdin` | `Get-Clipboard \| capellactl configure --api-key-stdin` |
| `~/capella-env` | `~\capella-env` |
| `capellactl plan --detailed-exitcode \|\| [ $? -eq 2 ]` | `capellactl plan --detailed-exitcode; if ($LASTEXITCODE -notin 0, 2) { exit $LASTEXITCODE }` |
| `capellactl completion zsh` | not available in PowerShell |

The **When something goes wrong** section gets a Windows bullet: `capellactl` is not recognized (activate again in
the new window, or use `.venv\Scripts\capellactl.exe`), and the execution-policy message.

### downloads/README.md (generated by `scripts/update-downloads.py`)
After the Windows unblock line, add how to install the `.exe` for the current user:

```powershell
mkdir $env:LOCALAPPDATA\Programs\capellactl -Force
Move-Item .\capellactl-*-windows-x86_64.exe $env:LOCALAPPDATA\Programs\capellactl\capellactl.exe
[Environment]::SetEnvironmentVariable("Path", "$([Environment]::GetEnvironmentVariable('Path','User'));$env:LOCALAPPDATA\Programs\capellactl", "User")
# open a new PowerShell window, then:
capellactl --version
```

No administrator rights are needed. The root README's Download block is regenerated from the same template.

### `help ci`
Add a Windows runner row next to the GitHub Actions example (`shell: pwsh`, the `$LASTEXITCODE` check above).

## Acceptance criteria & tests

### AC1 — The README has a Windows install table
**Given** `README.md`, **then** **Install** contains an **On Windows (PowerShell)** subsection with the table between
the `windows-install` markers. The table covers each step from installing Git and Python 3.12 to `capellactl --version`
and making the environment folder. Each row says what the user should see, and the rows for steps that can fail say
what to do (Python version, execution policy, `&&`).

| Test | Location | Verifies |
|---|---|---|
| `test_windows_docs_ac1_readme_install_table` | `tests/unit/docs/test_windows_docs.py` | Markers present; steps include `py -3.12`, `.venv\Scripts\python -m pip install -e .`, `Set-ExecutionPolicy -Scope CurrentUser`, `Activate.ps1`, `capellactl --version` |

### AC2 — The Windows commands contain nothing that only works in bash
**Given** every command in the Windows table, the PowerShell translation table, `downloads/README.md`'s PowerShell
block and `help ci`'s Windows example, **then** none uses `&&`, `||`, `export `, `source `, `.venv/bin`, a trailing `\`,
`pbpaste`, `python3` or a bare `curl `.

| Test | Location | Verifies |
|---|---|---|
| `test_windows_docs_ac2_bash_only_syntax_is_caught` | `tests/unit/docs/test_windows_docs.py` | Each forbidden pattern is caught in a deliberately bad example |
| `test_windows_docs_ac2_no_bash_only_syntax` | `tests/unit/docs/test_windows_docs.py` | None appears in the 27 Windows commands of the README, guide, downloads README and `help ci` |

### AC3 — The steps run as written on Windows PowerShell 5.1
**Given** a `windows-latest` runner, **when** a CI job extracts the README table's commands and runs them in
Windows PowerShell 5.1 (`shell: powershell`, not `pwsh`), **then** `capellactl --version` succeeds. Step 1
(`winget`) is skipped because the runner image already has Git and Python, and step 6 uses `-Scope Process`. A
change to the README table changes what CI runs.

| Test | Location | Verifies |
|---|---|---|
| `windows-install` job | `.github/workflows/ci.yml` | Commands come from the README (`scripts/readme-windows-steps.py`), not a copy |
| `test_windows_docs_ac3_steps_extracted_from_readme` | `tests/unit/docs/test_windows_docs.py` | The extractor returns the table's commands in order and drops only step 1 |
| `test_windows_docs_ac3_ci_runs_the_readme_in_windows_powershell` | `tests/unit/docs/test_windows_docs.py` | The job exists, uses `shell: powershell` and runs the extracted script |

### AC4 — Piping the token from PowerShell works
**Given** an API Key Token piped by Windows PowerShell (`Get-Clipboard | capellactl configure --api-key-stdin`), which
adds a trailing CRLF and, with some `$OutputEncoding` settings, a UTF-8 BOM, **then** `configure` stores the token
without them, as it does for the pasted prompt.

| Test | Location | Verifies |
|---|---|---|
| `test_windows_docs_ac4_api_key_stdin_crlf_bom` | `tests/unit/cli/test_configure_key.py` | `clean_api_key` removes CRLF and BOM |
| `test_windows_docs_ac4_powershell_piped_key_stored_clean` | `tests/scenario/test_configure.py` | `"\ufeffKEY\r\n"` on stdin is stored in the keychain and sent to Capella as `KEY` |

### AC5 — Every bash-only construct in the docs has a PowerShell translation
**Given** the shell blocks in `README.md` Quick start, `docs/getting-started.md`, `docs/runbook.md` and `help ci`,
**then** every bash-only construct they use (`export`, a trailing `\`, `&&`, `||`, `pbpaste`, `curl -s`, `$?`) has a
row in the getting-started PowerShell table. A new doc that uses a construct the table lacks fails CI.

| Test | Location | Verifies |
|---|---|---|
| `test_windows_docs_ac5_translation_table_complete` | `tests/unit/docs/test_windows_docs.py` | |

### AC6 — The `.exe` can be run as `capellactl` from any folder
**Given** the generated `downloads/README.md`, **then** its Windows section explains how to put the executable on the
user PATH as `capellactl.exe` without administrator rights. `scripts/update-downloads.py --check` stays green.

| Test | Location | Verifies |
|---|---|---|
| `test_windows_docs_ac6_exe_on_user_path` | `tests/unit/docs/test_windows_docs.py` | The generated README has the user-PATH block, never the machine PATH |

## Out of scope
- A Windows installer (MSI), winget or Chocolatey package, or Scoop manifest (CAP-045 out of scope).
- PowerShell tab completion (Click has none).
- Windows copies of the getting-started guide or the runbook. The translation table covers them.
- WSL. WSL users follow the Linux steps as they are.
- cmd.exe beyond the activation line. PowerShell is the documented shell.

## Open questions
- Does `py -3.12` find the Python that `actions/setup-python` installs on the `windows-latest` runner? The AC3 job
  checks first and, if it does not, passes setup-python's interpreter with `--python` and says so in its log. The
  README keeps `py`. To be confirmed by the job's first run.
- ~~Lead with activation (`Set-ExecutionPolicy`) or with `.venv\Scripts\capellactl.exe`?~~ Decided (2026-10-29):
  activation first, so the commands match the rest of the docs; the full path is offered in the same row for
  laptops whose policy cannot be changed.
- ~~Run the time-to-first-environment check once on Windows before 1.0.0?~~ Decided (2026-10-29): yes; added to the
  release checklist in `scripts/update-story-index.py`.

## Implementation notes (as built)
- README **Install** → **On Windows (PowerShell)**: the 9-step table as designed, between the `windows-install`
  markers. The macOS/Linux steps now say they are for macOS and Linux and link to it; the old one-line Windows note is
  gone.
- `docs/getting-started.md` → **Before you start** → **Using the commands in PowerShell** (between the
  `powershell-translation` markers), linked from the README and the runbook. Scanning the docs found two constructs
  the draft lacked: `"$(curl -s …)/32"` inside `cidr create` (the row now shows that exact form; `"$(…)"` works the
  same in PowerShell, only `curl` must be `curl.exe`) and `\` continuations in `docs/custom-clusters.md`, which the
  AC5 scan now covers too. The `&&` row's note was dropped: the README table explains it.
- Troubleshooting has a Windows bullet (`capellactl is not recognized`, `running scripts is disabled`), and the API
  key bullet gives the PowerShell IP check.
- AC4 was a real defect: `clean_api_key` stripped the CRLF but kept a UTF-8 BOM (`\ufeff` is not whitespace to
  `str.strip`), so a token piped from Windows PowerShell with a UTF-8 `$OutputEncoding` would be rejected. It now
  removes it and notes `removed a byte-order mark`.
- `scripts/readme-windows-steps.py` builds the CI script from the README table. It skips step 1 (winget), clones the
  checked-out commit instead of GitHub's `main` (`git clone "<checkout>" capellactl`), and runs step 6 with
  `-Scope Process … -Force`. It first sets the process policy to `Restricted`, as on a new laptop, so `Activate.ps1`
  runs only if the README's policy step works. Each command is checked (`$?` and `$LASTEXITCODE`), because Windows
  PowerShell does not stop when a program fails. The file is written as UTF-8 with a BOM, which Windows PowerShell
  5.1 needs to read non-ASCII text.
- `windows-install` CI job (after `test`, on `windows-latest`, `shell: powershell`). It is not one of the six
  required checks in the `main` ruleset (CAP-050); add it there if a red run should block merging.
- `help ci` has the Windows runner gate; `downloads/README.md` (generated) has the user-PATH install for the `.exe`.
- Not run here: the Windows job itself (no Windows machine); the unit tests run on every OS in the `test` matrix.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_windows_docs_ac1_readme_install_table` |
| AC2 | `test_windows_docs_ac2_bash_only_syntax_is_caught`, `test_windows_docs_ac2_no_bash_only_syntax` |
| AC3 | `test_windows_docs_ac3_steps_extracted_from_readme`, `test_windows_docs_ac3_ci_runs_the_readme_in_windows_powershell`; `windows-install` CI job |
| AC4 | `test_windows_docs_ac4_api_key_stdin_crlf_bom`, `test_windows_docs_ac4_powershell_piped_key_stored_clean` |
| AC5 | `test_windows_docs_ac5_translation_table_complete` |
| AC6 | `test_windows_docs_ac6_exe_on_user_path` |
