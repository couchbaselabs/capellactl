# CAP-062 — Config problems say where they are, whether this command caused them, and how to fix them

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E1 Foundation | P1 | 5 | CAP-002, CAP-038, CAP-054 | Implemented |

## User story
As an **operator running any capellactl command**, I want a problem in `capella.yaml` to be reported with the names
of the project, cluster, bucket or credential it is in, whether my command caused it, and a command that fixes it,
so that I can fix it without reading YAML index paths or editing the file by hand.

## Context & discovery
- Reported by a customer (2026-10-30). `capellactl cluster create test-01 --project sandbox …` printed:
  ```
  capella.yaml already has problems; fix them first, then run cluster create again:
  projects[1].clusters[0].allowedCidrs[0].cidr: 0.0.0.0/0 allows every IP address; add allowAnyIp: true to cluster 'ct-n-zeaus-mktfareevl-stg' to confirm (line 34)
  projects[1].clusters[2].allowedCidrs[2].cidr: 0.0.0.0/0 allows every IP address; add allowAnyIp: true to cluster 'NonProd-dev' to confirm (line 256)
  …
  ```
  Four problems with this:
  1. **Index paths.** `projects[1].clusters[2].allowedCidrs[2]` makes the reader count list entries in the file. The
     project, cluster and IP range have names.
  2. **A hand edit as the fix.** "add allowAnyIp: true" contradicts the docs ("you never edit `capella.yaml`"), and a
     command can fix it: `sync` records `allowAnyIp: true` when Capella already allows `0.0.0.0/0` (fixed in import
     the same day), and `cidr delete` stops allowing it.
  3. **No link to the command.** The three clusters are in project `non-prod`, not in `test-01`; nothing says the
     command did not cause them.
  4. **The same applies everywhere.** Every command shows config problems through `ConfigError` (`validate`, `plan`,
     `apply`, and every resource command through `change_and_apply`), so the fix belongs there, not in
     `cluster create`.
- Each problem is built in one of three places: schema errors and secret references in `config/loader.py`, and
  cross-reference rules in `config/crossref.py` (one `add()`). The index path (`ConfigIssue.path`) is still needed
  internally, for example `cluster create` uses it to tell which answer to ask for again (CAP-038 AC4).
- Three messages ask for a hand edit: the any-IP rule and a credential's undefined bucket ("set external: true") in
  `crossref.py`, and the planner's duplicate-name block ("add id:"). `sync` already gives a command for the same
  duplicate-name case ("capellactl sync --force").

## Design

### How a problem is shown
```
capella.yaml already had 3 problems before this command, so nothing was changed. Fix them, then run the command again:
  project non-prod › cluster ct-n-zeaus-mktfareevl-stg › allowed IP range 0.0.0.0/0 (line 34)
    0.0.0.0/0 lets every IP address connect, and capella.yaml does not record that this is intended
    fix: 'capellactl sync --project non-prod' records what Capella allows, or 'capellactl cidr delete ct-n-zeaus-mktfareevl-stg 0.0.0.0/0' stops allowing it
  …
See: capellactl help safety
```
- **Where**: the resources the problem is in, by name, from the outside in: `project`, `cluster`, `service group`
  (its services), `bucket`, `scope`, `collection`, `credential`, `allowed IP range` (its CIDR). Then the field inside
  the last resource, when it is not the resource's own name (`… › service group data › numOfNodes`), and the line.
  An entry without a name is shown by its position (`cluster #3`). A problem outside any resource keeps its field
  path (`apiVersion`).
- **Problem**: the message, unchanged unless this story rewrites it (AC4).
- **Fix** (optional): a capellactl command, never an edit of the file.
- **Heading**: depends on who caused the problems (AC3):
  - `validate`, `plan`, `apply` and anything that loads the file: `capella.yaml has N problem(s):`
  - A command whose change causes the problems: `This change is not valid, so nothing was changed:`
  - A command that changes nothing wrong itself, run while the file already has problems: the heading in the
    example above.
  - Both: the command's own problems first, then `Already in capella.yaml before this command:` and the others.
- **Duplicates** name the line of the first entry (`also on line 12`) instead of a list index.

### Where the code goes
- `config/loader.py`: `ConfigIssue` gains `where` and `fix`; `describe(data, path)` builds `where`; `ConfigError`
  renders the heading and the entries; `load_config` fills `where` before raising.
- `config/crossref.py`: `add()` takes `fix`; the any-IP and undefined-bucket messages give commands; duplicates name
  the line.
- `cli/cluster_ops.py`: `_validate_candidate` compares the problems of the new text with those of the file as it was
  before the command (by `where` and message) and picks the heading. The CAP-038 re-ask reads the problems' paths,
  not the message text. `cluster create` checks the file before its first question (as built on 2026-10-30).
- `engine/planner.py`: the duplicate-name block gives `capellactl sync --force` like `sync` does.

## Acceptance criteria & tests

### AC1 — Named location
**Given** a cluster `nova-dev-01` in project `nova-dev` that allows `0.0.0.0/0` without `allowAnyIp`, or a service
group with too few nodes, or a credential that names an undefined bucket, **then** loading the file fails (exit 3 in
every command) and names the problem as `project nova-dev › cluster nova-dev-01 › allowed IP range 0.0.0.0/0`,
`… › service group data,index,query › numOfNodes` or `… › credential app › access[0].resources.buckets[0].name`, with
its line, and no index path such as `projects[0].clusters[0]` appears.

| Test | Location | Verifies |
|---|---|---|
| `test_config_errors_ac1_named_location` | `tests/unit/config/test_error_messages.py` | The three locations, lines, no index paths |
| `test_config_errors_ac1_unnamed_and_root` | same | `cluster #2` for an entry without a name; `apiVersion` stays a field |

### AC2 — Counted, one block per problem
**Given** a file with two problems, **then** every command that loads it prints `capella.yaml has 2 problems:` and
one block per problem in file order: location and line, the problem, and its fix when it has one.

| Test | Location | Verifies |
|---|---|---|
| `test_config_errors_ac2_heading_and_blocks` | `tests/unit/config/test_error_messages.py` | Heading, order, fix line |
| `test_config_errors_ac2_same_in_plan` | `tests/scenario/test_error_messages.py` | `plan` shows the same blocks |

### AC3 — Says whether this command caused it
**Given** a file that already has a problem in another project, **when** `cluster create` runs, **then** it exits 3
before asking anything, with the "already had 1 problem before this command" heading, and the file is unchanged.
**Given** a valid file and a `cluster create --cidr` that overlaps another cluster, **then** the heading is "This change
is not valid". **Given** both (a file with an invalid support plan, and `bucket backup schedule set
--incremental-every 3`), **then** the command's own problem is listed first, then the existing one under "Already
in capella.yaml before this command".

| Test | Location | Verifies |
|---|---|---|
| `test_config_errors_ac3_existing_problems` | `tests/scenario/test_error_messages.py` | No question asked, file unchanged |
| `test_config_errors_ac3_caused_by_change` | same | |
| `test_config_errors_ac3_both` | same | Order and both headings |

### AC4 — The fix is a command, never a hand edit
**Given** the any-IP problem (a warning since CAP-022 AC5 was revised), **then** its action names `capellactl sync
--project P` and `capellactl cidr delete CLUSTER 0.0.0.0/0`. **Given** a credential whose bucket is not in the file, **then** the fix names
`capellactl sync --project P` and `capellactl bucket create CLUSTER BUCKET`. **Given** the planner's duplicate-name
block, **then** it names `capellactl sync --force`. No message in `capellactl/` asks the reader to add or set a field
in the file.

| Test | Location | Verifies |
|---|---|---|
| `test_config_errors_ac4_fix_commands` | `tests/unit/config/test_error_messages.py` | Any-IP and bucket fixes |
| `test_config_errors_ac4_no_hand_edit_advice` | same | Scans the message strings of `capellactl/` |

### AC5 — Asking again still works
**Given** an interactive `cluster create` whose prompted CIDR is not a network address, **then** only the CIDR is
asked again (CAP-038 AC4 keeps passing); **given** Azure and size `dev` (AWS only), **then** the problem is shown in
the new format and the provider and size are asked again.

| Test | Location | Verifies |
|---|---|---|
| `test_cluster_create_ac4_interactive_reasks` | `tests/scenario/test_cluster_cli.py` | Existing CAP-038 test, unchanged |
| `test_config_errors_ac5_reask_provider_and_size` | `tests/scenario/test_error_messages.py` | Provider and size asked again |

## Out of scope
- Messages from Capella's API (`CapellaApiError`): they already show Capella's message and hint.
- `-o json` output for errors: errors go to stderr as text today; a JSON error format is a separate change.

## Implementation notes (as built)
- `ConfigIssue.where` is filled by `describe()` in `load_config`, from the file's data and the index path, so every
  rule (schema, secrets, cross-references) gets it without changing how the rule reports. `ConfigIssue.path` stays the
  index path for code that needs it.
- Problems are found in stages: YAML, `apiVersion`, then secrets and schema, then cross-references. A later stage runs
  only when the earlier ones pass, so a file can show schema problems first and cross-reference problems after they
  are fixed. AC3's "both" test uses two schema problems for that reason.
- "Already in the file" compares problems by location and message, not by index path, so adding or removing a
  cluster does not make an old problem look new.
- Besides the three hand-edit messages named above, two more were found by the AC4 scan and fixed: the comment
  import writes above each credential ("add password: …", now `credential update … --password-env VAR
  --rotate-password`), and `sync`'s duplicate project name message ("add id: to it").
- Tests: AC1 `test_config_errors_ac1_named_location`, `test_config_errors_ac1_unnamed_and_root`; AC2
  `test_config_errors_ac2_heading_and_blocks`, `test_config_errors_ac2_same_in_plan`; AC3
  `test_config_errors_ac3_existing_problems`, `test_config_errors_ac3_caused_by_change`, `test_config_errors_ac3_both`;
  AC4 `test_config_errors_ac4_fix_commands`, `test_config_errors_ac4_no_hand_edit_advice`; AC5
  `test_cluster_create_ac4_interactive_reasks`, `test_config_errors_ac5_reask_provider_and_size`. 21 existing tests
  were updated from the `path: message` form to the new blocks.
