# Exit codes

| Code | Meaning |
|---|---|
| 0 | Success, or nothing to do |
| 1 | Runtime or API error |
| 2 | `plan` / `drift` with `--detailed-exitcode` found changes; also unknown commands or bad flags |
| 3 | Configuration invalid (schema, references, secrets, missing API key or organization) |
| 4 | Blocked (immutable change, deletion protection, unsafe scale-in, cluster turned off, ambiguous name) |
| 5 | Timed out waiting for Capella (the operation continues; re-run to resume waiting) |
| 130 | Interrupted |
