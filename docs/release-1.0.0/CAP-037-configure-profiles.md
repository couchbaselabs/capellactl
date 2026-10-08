# CAP-037 — `configure`: profiles, API key storage & config discovery

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P1 | 3 | CAP-003, CAP-008 | Implemented |

## User story
As an **operator who manages several Capella organizations or environments**, I want to save my organization and API key once per profile and switch between them, so that I do not export environment variables before every command and the key is still stored securely.

## Context & discovery
- 1.0.0 originally read the API key only from `CAPELLA_API_KEY`. That stays supported (CI), but interactive users need something simpler.
- The key must never be stored in plain text or in `capella.yaml`. The OS keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service) via the `keyring` library meets that.
- `GET /v4/organizations` returns the organizations the key can see (`id`, `name`), which lets `configure` verify the key and offer a choice.

## Implementation details

### Commands
```
capellactl configure [--profile dev]          # interactive: API key (hidden), verify, choose org, defaults
capellactl configure list                     # profiles: name, org, base URL, default config file
capellactl configure show [--profile dev]     # key shown as ••••last4
capellactl configure remove --profile dev
capellactl --profile prod plan                # or CAPELLACTL_PROFILE=prod
```

### Storage
| What | Where |
|---|---|
| Profile settings (`organizationId`, `apiBaseUrl`, `configFile`) | `~/.config/capellactl/profiles.yaml` (Windows: `%APPDATA%\capellactl\profiles.yaml`), mode `0600` |
| API key | OS keychain, service `capellactl`, account `<profile>` |

No keychain backend available → `configure` refuses to store the key and explains how to use `CAPELLA_API_KEY` instead.

### Precedence (highest first)
1. Command-line flags (`--config`, `--profile`)
2. Environment variables (`CAPELLA_API_KEY`, `CAPELLA_ORG_ID`, `CAPELLA_API_BASE_URL`, `CAPELLACTL_CONFIG`)
3. Selected profile (`--profile`, `CAPELLACTL_PROFILE`, else `default`)
4. `organizationId` in `capella.yaml`

### Config file discovery
`--config` → `CAPELLACTL_CONFIG` → profile `configFile` → `./capella.yaml` → `./capella.yml`. Both present in the same directory → exit 3 `both capella.yaml and capella.yml found; pass --config`.

## Acceptance criteria & tests

### AC1 — Configure verifies and saves
**Given** a valid key typed at a hidden prompt, **then** `configure` calls `GET /v4/organizations`, lists the organizations to choose from, saves the profile file (mode `0600`) and the key in the keychain, and prints `profile 'default' saved (org Nova Corp)`. The key is never echoed.

| Test | Location | Verifies |
|---|---|---|
| `test_configure_ac1_saves_profile_and_keychain` | `tests/scenario/test_configure.py` | `keyring` test backend |
| `test_configure_ac1_key_not_echoed` | same | `assert_no_secret` |

### AC2 — Invalid key is not saved
**Given** the organizations call returns `401`, **then** nothing is saved and the command exits 1 `API Key Token rejected by Capella …` (details in AC7).

| Test | Location | Verifies |
|---|---|---|
| `test_configure_ac2_invalid_key_not_saved` | `tests/scenario/test_configure.py` | |

### AC3 — Precedence
**Given** a profile with org A and `CAPELLA_ORG_ID=B`, **then** B is used; **given** `--profile prod`, **then** prod's key and org are used unless overridden by env vars. `capellactl configure show` lists the effective value and its source for each setting.

| Test | Location | Verifies |
|---|---|---|
| `test_configure_ac3_precedence_matrix` | `tests/unit/config/test_precedence.py` | Parametrised table |
| `test_configure_ac3_show_sources` | `tests/scenario/test_configure.py` | |

### AC4 — No keychain
**Given** no keychain backend, **then** `configure` saves the profile without the key and prints `no OS keychain available; set CAPELLA_API_KEY in your environment instead`; the key is never written to disk.

| Test | Location | Verifies |
|---|---|---|
| `test_configure_ac4_no_keychain_never_writes_key` | `tests/scenario/test_configure.py` | Scans written files for the key |

### AC5 — Config file discovery
**Given** only `capella.yml` in the working directory, **then** it is used; **given** both `.yaml` and `.yml`, **then** exit 3 with the message above; **given** a profile `configFile`, **then** it is used when no flag or env var is set.

| Test | Location | Verifies |
|---|---|---|
| `test_discovery_ac5_yml_used` | `tests/unit/config/test_discovery.py` | |
| `test_discovery_ac5_both_present_error` | same | |
| `test_discovery_ac5_profile_config_file` | same | |

### AC6 — Remove
**Given** `configure remove --profile dev`, **then** the profile entry and its keychain item are deleted; removing a missing profile exits 0 with `nothing to remove`.

| Test | Location | Verifies |
|---|---|---|
| `test_configure_ac6_remove_profile_and_key` | `tests/scenario/test_configure.py` | |

### AC7 — Paste-safe key entry and clear rejection
**Given** a pasted key wrapped in quotes, prefixed with `Bearer `, split by line breaks or wrapped in terminal paste markers, **then** `configure` cleans it and says what it removed (never the key). **Given** Capella rejects the key (401), **then** nothing is saved and the output shows Capella's own `hint`, the received key's length and last 4 characters, a checklist (API key IP allowlist, API Key Token vs API Key ID, expiry, API URL), a `curl` command to test the key without capellactl, and the `--api-key-stdin` alternative. **Given** `--api-key-stdin`, **then** the key is read from standard input; with several organizations visible, `--org-id` is required (exit 3 listing them).

| Test | Location | Verifies |
|---|---|---|
| `test_configure_ac7_cleans_pasted_key` | `tests/unit/cli/test_configure_key.py` | Parametrised damage cases |
| `test_configure_ac7_rejection_shows_hint_and_checklist` | `tests/scenario/test_configure.py` | Nothing saved |
| `test_configure_ac7_api_key_stdin` | `tests/scenario/test_configure.py` | Single and several organizations |

## Out of scope
- SSO or OAuth login (the Management API uses API keys).
- Creating API keys through the API (needs an existing key; candidate for 1.1).

## Open questions
- Is the `keyring` dependency acceptable on the customer's locked-down Linux jump hosts? If not, ship it as an optional extra (`pipx install 'capellactl[keyring]'`).

## Implementation notes (as built)
- Profiles live in `$CAPELLACTL_HOME/profiles.yaml` (default `~/.config/capellactl`, `%APPDATA%\capellactl` on Windows), mode 0600. The API key is only in the OS keychain.
- AC7 was added after the first real-world run: a pasted key was rejected and the original message hid Capella's hint (the API key IP allowlist). Capella's real 401 body is now mirrored by the fake.
- `keyring` is a regular dependency; when no keychain backend exists, `configure` saves the profile without the key and says to use `CAPELLA_API_KEY`.

### Tests by AC

| AC | Tests |
|---|---|
| AC1 | `test_configure_ac1_saves_profile_and_keychain` (tests/scenario/test_configure.py)<br>`test_configure_ac1_key_not_echoed` (tests/scenario/test_configure.py) |
| AC2 | `test_configure_ac2_invalid_key_not_saved` (tests/scenario/test_configure.py) |
| AC3 | `test_configure_ac3_show_sources` (tests/scenario/test_configure.py)<br>`test_configure_ac3_profile_used_by_commands` (tests/scenario/test_configure.py)<br>`test_configure_ac3_precedence_matrix` (tests/unit/config/test_precedence.py) |
| AC4 | `test_configure_ac4_no_keychain_never_writes_key` (tests/scenario/test_configure.py) |
| AC5 | `test_discovery_ac5_yml_used` (tests/unit/config/test_discovery.py)<br>`test_discovery_ac5_both_present_error` (tests/unit/config/test_discovery.py)<br>`test_discovery_ac5_profile_config_file` (tests/unit/config/test_discovery.py)<br>`test_discovery_ac5_both_present_cli_exit_3` (tests/unit/config/test_discovery.py) |
| AC6 | `test_configure_ac6_remove_profile_and_key` (tests/scenario/test_configure.py)<br>`test_configure_ac6_list` (tests/scenario/test_configure.py) |
