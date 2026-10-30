# CAP-081 — Alert integrations

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E15 Observability & cost | P1 | 5 | CAP-009, CAP-008 | Not started |

## User story
As an **operator**, I want to send a project's Capella alerts to Slack, Microsoft Teams or a webhook, declared in
capella.yaml, so that every environment alerts the right on-call channel from day one.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Create | `POST …/projects/{p}/alertIntegrations` | 201 | `kind` (`webhook`, `slack`, `teams`), `name`, `config.{webhook|slack|teams}` → `id` |
| List | `GET …/projects/{p}/alertIntegrations` | 200 | `status`, `enabled`, `configKey` |
| Get | `GET …/alertIntegrations/{id}` | 200 | Secrets are not returned |
| Update | `PUT …/alertIntegrations/{id}` | 200 | `name`, `enabled`, `config` |
| Delete | `DELETE …/alertIntegrations/{id}` | 204 | |
| Slack channels | `POST …/alertIntegrations/channels` | 200 | `botToken` or `integrationId` → `channels[]` |
| Test | `POST …/projects/{p}/alertIntegrationTest` | 202 | `kind`, `config` |

Webhook `config`: `method` (`POST`, `PUT`), `url`, `token` or `basicAuth`, `headers`, `exclude`,
`customPayloads`. Slack: `webhookURL` or `botToken` + `channel`. Teams: `url`. URLs with embedded tokens, bot
tokens and passwords are secrets: `${env:…}` references only in capella.yaml (CAP-002) and redacted (CAP-008).

## Design

### Commands
```
capellactl alert list     [--project NAME]
capellactl alert get      NAME
capellactl alert create   NAME --slack-webhook URL | --slack-bot-token T --channel C | --teams-url URL | --webhook URL [--method POST|PUT] [--header K=V …]
capellactl alert update   NAME [--enable|--disable] [config flags]
capellactl alert delete   NAME
capellactl alert channels --bot-token T | NAME
capellactl alert test     NAME | (config flags)
```
Example:
```
capellactl alert create oncall-slack --slack-webhook "$SLACK_WEBHOOK_URL"
capellactl alert test oncall-slack
```

### capella.yaml
```yaml
projects:
  - name: nova
    alertIntegrations:
      - name: oncall-slack
        slack: {webhookUrl: "${env:SLACK_WEBHOOK_URL}"}
        enabled: true
```
- Because Capella does not return secrets, a secret is compared through a hash stored next to capella.yaml in
  `.capellactl/state` (as CAP-028 does for passwords); a changed secret is an update.
- `create` and `update` from the CLI write the `${env:…}` reference, never the value; the flag value must come from
  an environment variable or `-` (stdin).
- Code: `cli/alert_cmds.py`, `resources/alert_integration.py` (project child, prunable), seven operations.

## Acceptance criteria & tests

### AC1 — Create from capella.yaml
**Given** the block above with `SLACK_WEBHOOK_URL` set, **then** one `POST` with `kind: slack` and the URL; the URL
appears in no output or log; `plan` then reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_alert_ac1_create_slack` | `tests/scenario/test_alert_integrations.py` | `assert_no_secret` |
| `test_alert_ac1_create_webhook_teams` | same | Parametrised bodies |

### AC2 — Idempotent
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_alert_ac2_rerun_zero_writes` | `tests/scenario/test_alert_integrations.py` | |

### AC3 — Plain-text secret refused
**Given** a literal webhook URL, bot token or password in capella.yaml, **then** `validate` exits 3 with the CAP-002
secret message.

| Test | Location | Verifies |
|---|---|---|
| `test_alert_ac3_plain_secret_refused` | `tests/unit/config/test_alert_rules.py` | |

### AC4 — Update, disable, delete
**Given** `enabled: false` or a changed secret, **then** one `PUT`; `alert delete` asks once; re-run prints `not
found, nothing to do`.

| Test | Location | Verifies |
|---|---|---|
| `test_alert_ac4_update_disable_delete` | `tests/scenario/test_alert_integrations.py` | |

### AC5 — Test and channels
**Given** `alert test oncall-slack`, **then** one `POST …/alertIntegrationTest` and `test alert sent`; `channels`
prints `S.NO`, `NAME`, `TYPE`, `ID`.

| Test | Location | Verifies |
|---|---|---|
| `test_alert_ac5_test_and_channels` | `tests/scenario/test_alert_integrations.py` | |

### AC6 — List, sync, drift
**Given** integrations in Capella, **then** `list` prints `S.NO`, `NAME`, `KIND`, `ENABLED`, `STATUS`, `ID`; `sync`
writes them with `${env:…}` placeholders for secrets and warns which variables to set; `drift` lists unmanaged ones.

| Test | Location | Verifies |
|---|---|---|
| `test_alert_ac6_list_sync_drift` | `tests/scenario/test_alert_integrations.py` | |

## Out of scope
- Choosing which alert types are sent (not in the API).

## Open questions
- Does `PUT` require the full secret again when only `enabled` changes? If so, AC4 needs the environment variable
  for every update.
