# CAP-083 — Billing reports

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E15 Observability & cost | P2 | 3 | CAP-003 | Not started |

## User story
As a **billing admin**, I want to see and download what my organization, projects and clusters cost from the
terminal, so that I can track spend in scripts and spreadsheets without the UI.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Categorized | `POST {org}/billing` | 200 | `startDate`, `endDate`, `filters` (`categories`, `projectIds`, `instanceIds`) → `periods`, `total`, `billingCurrency` |
| Itemized per cluster | `POST …/clusters/{c}/billing` | 200 | `startDate`, `endDate`, `filters.categories` |
| Prepaid credits | `GET {org}/billing/prePaidCredits` | 200 | `creditName`, `supportPlan`, `total`, `used`, `remaining`, `expirationDate` |
| Pay as you go | `GET {org}/billing/payAsYouGo` | 200 | `startDate`, `endDate` params |
| Download categorized | `POST {org}/billing/download` | 200 | Binary (CSV) |
| Download itemized | `POST …/clusters/{c}/billing/download` | 200 | Binary (CSV) |

Categories include `operationalComputeAndStorage`, `operationalBucketBackup`, `operationalClusterBackup`,
`dataTransferStandard`, `privateEndpointsStandard`, `dataApiStandard` and others listed in the spec. Needs an
Organization Owner or billing role.

## Design
```
capellactl billing get      [--from DATE] [--to DATE] [--project NAME …] [--cluster NAME] [--category C …]
capellactl billing prepaid
capellactl billing payg     [--from DATE] [--to DATE]
capellactl billing download --out FILE [--from DATE] [--to DATE] [--project NAME …] [--cluster NAME] [--category C …]
```
Example:
```
capellactl billing get --from 2026-10-01 --to 2026-10-31 --project nova
capellactl billing download --cluster nova-prod-01 --out nova-prod-01-oct.csv
```
- Default range is the current calendar month. `--cluster` switches `get` and `download` to the itemized cluster
  endpoints (with `--project` to find it).
- `get` prints one row per category with credits and currency, then the total.
- Read-only. Code: `cli/billing_cmds.py`, six operations, fake Capella.

## Acceptance criteria & tests

### AC1 — Categorized report
**Given** `billing get --from 2026-10-01 --to 2026-10-31 --project nova`, **then** one `POST {org}/billing` with the
dates and `projectIds`, and a table `S.NO`, `CATEGORY`, `CREDITS`, `COST` with a total line.

| Test | Location | Verifies |
|---|---|---|
| `test_billing_ac1_categorized` | `tests/scenario/test_billing.py` | |

### AC2 — Itemized per cluster
**Given** `--cluster nova-prod-01`, **then** the cluster endpoint is used and the table names the support plan.

| Test | Location | Verifies |
|---|---|---|
| `test_billing_ac2_itemized` | `tests/scenario/test_billing.py` | |

### AC3 — Credits and pay-as-you-go
**Given** `prepaid` and `payg`, **then** prepaid prints `S.NO`, `NAME`, `PLAN`, `USED`, `REMAINING`, `EXPIRES`,
`ID`; payg prints the period totals.

| Test | Location | Verifies |
|---|---|---|
| `test_billing_ac3_prepaid_payg` | `tests/scenario/test_billing.py` | |

### AC4 — Download
**Given** `download --out FILE`, **then** the body is written byte for byte; an existing different file is not
overwritten without `--force`.

| Test | Location | Verifies |
|---|---|---|
| `test_billing_ac4_download` | `tests/scenario/test_billing.py` | |

### AC5 — Validation and read-only
**Given** `--to` before `--from`, an unknown category or a category not allowed for a cluster report, **then** exit 3;
any run makes zero `PUT`/`DELETE` calls and only the documented `POST` reads.

| Test | Location | Verifies |
|---|---|---|
| `test_billing_ac5_validation_read_only` | `tests/scenario/test_billing.py` | |

## Out of scope
- Budgets and cost alerts (not in the API).

## Open questions
- What is the longest date range one request accepts?
