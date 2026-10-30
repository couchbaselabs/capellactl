# CAP-073 — Download a cluster's CA certificate

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E12 Replication & cluster operations | P1 | 1 | CAP-038 | Not started |

## User story
As a **developer**, I want to save my cluster's CA certificate to a file, so that my SDK can verify the TLS
connection without copying the certificate from the Capella UI.

## Context & discovery
- `GET …/clusters/{clusterId}/certificates` → 200 `{certificate: "<PEM>"}`.

## Design
```
capellactl cluster certificate CLUSTER [--out FILE]
```
Example:
```
capellactl cluster certificate nova-dev-01 --out nova-dev-01-ca.pem
```
- Without `--out`, prints the PEM to stdout (so it can be piped); with `-o json`, Capella's body.
- With `--out`, writes the file (refuses to overwrite a different file without `--force`) and prints its path and
  the certificate's expiry date.
- Code: `cli/cluster_ops.py` gains `certificate`; one operation; the fake returns a fixed PEM.

## Acceptance criteria & tests

### AC1 — Print and save
**Given** a healthy cluster, **then** the PEM is printed; with `--out` it is written and `saved CA certificate to
nova-dev-01-ca.pem (expires 2036-01-01)` is printed.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_certificate_ac1_print_and_save` | `tests/scenario/test_cluster_certificate.py` | |

### AC2 — Overwrite protection
**Given** `--out` names an existing file with different content, **then** exit 1 without writing, unless `--force`.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_certificate_ac2_no_overwrite` | `tests/scenario/test_cluster_certificate.py` | |

### AC3 — Read-only
**Given** any run, **then** zero `POST`/`PUT`/`DELETE` calls.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_certificate_ac3_read_only` | `tests/scenario/test_cluster_certificate.py` | |

## Out of scope
- Client certificates (the API has none).

## Open questions
- None.
