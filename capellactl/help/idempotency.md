# Idempotency: plan and apply

capellactl keeps no state file. Each run reads Capella, compares it with the file, and makes only
the changes needed. Running `apply` twice makes no changes the second time.

**Plan symbols**

| Symbol | Meaning |
|---|---|
| `+` | will be created |
| `~` | will be changed in place (field `before → after` follows) |
| `±` | will be re-created (allowed CIDRs only; the API has no update) |
| `-` | will be deleted (only with delete, destroy or --prune) |
| `=` | already matches |
| `!` | blocked: cannot be applied; apply refuses to start |
| `…` | deferred: waits on its parent (for example a cluster that is not healthy yet) |

**How resources are matched**: by name. Capella allows two projects or clusters with the same name;
then the item is blocked until you add `id:` to pick one.

**What is compared**: only fields you wrote in the file. Omitted fields keep their current values.
Order of lists such as services and service groups does not matter. Passwords are never compared
(Capella never returns them).

**Immutable fields** (cloud, region, availability, server version, bucket storage engine, …) are never
changed by deleting and recreating; the change is blocked instead.
