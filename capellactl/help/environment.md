# Environment, profiles and precedence

**Profiles**: `capellactl configure [--profile NAME]` verifies an API key, lets you pick the
organization, saves settings in `~/.config/capellactl/profiles.yaml` and the key in the OS keychain.
Switch with `--profile NAME` or `CAPELLACTL_PROFILE`. `capellactl configure show` prints every
effective setting and where it came from.

**If the key is rejected (401)**: check the API key's allowed IP list includes this machine's public IP,
that you copied the **API Key Token** (not the API Key ID), and that it has not expired. Read the key from a pipe
instead of pasting: `pbpaste | capellactl configure --api-key-stdin`.

**Environment variables**

| Variable | Meaning |
|---|---|
| `CAPELLA_API_KEY` | API key (Bearer token) |
| `CAPELLA_ORG_ID` | Organization ID |
| `CAPELLA_API_BASE_URL` | Default `https://cloudapi.cloud.couchbase.com` |
| `CAPELLACTL_CONFIG` | Config file path |
| `CAPELLACTL_PROFILE` | Profile name |

`BEARER_TOKEN`, `ORG_ID` and `API_BASE_URL` (older scripts) still work, with a warning.

**Precedence** (highest first): command-line flags → environment variables → profile →
`organizationId` in the config file.

**API key roles**: Organization Owner, or Project Creator to create projects plus Project Owner or
Project Manager for clusters and their contents.
