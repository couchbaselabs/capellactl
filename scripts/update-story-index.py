#!/usr/bin/env python3
"""Regenerate docs/<release>/README.md from the story files' header tables.

Each story file (CAP-NNN-*.md) starts with:

    # CAP-NNN — Title
    | Epic | Priority | Points | Depends on | Status |
    |---|---|---|---|---|
    | E1 Foundation | P0 | 5 | CAP-001 | Not started |

Status must be one of: Not started, In progress, Implemented, Descoped.
Implemented stories are struck through in the priority tables and the phase overview (not in
the per-phase story tables, which have a Status column). Descoped stories keep their file and ID
(numbering stays gap-free) but don't count anywhere: they're listed in their phase's table and in
a "Descoped" section only.

Phases and the release checklist are per release (RELEASES below). Story IDs are numbered across
releases, so each release's IDs must be contiguous but needn't start at CAP-001.

Adapted from omni-data-bus/scripts/update-story-index.py.

Usage: python3 scripts/update-story-index.py [docs/release-1.0.0]
       python3 scripts/update-story-index.py --check [docs/release-1.0.0]   # CI: fail if README.md is stale
"""
import re
import sys
from collections import OrderedDict
from pathlib import Path

PREFIX = "CAP"
STATUSES = ("Not started", "In progress", "Implemented", "Descoped")


def priority_info(release: str) -> OrderedDict:
    minor = ".".join(release.split(".")[:2])
    return OrderedDict([
        ("P0", "Must have — release blocker"),
        ("P1", f"Should have — ships in {minor} unless explicitly descoped"),
        ("P2", "Nice to have"),
    ])


PRIORITY_INFO = priority_info("1.0.0")  # keys only, for validation

# Per-release configuration. Phases are in delivery order; each ends with something an operator can
# run against Capella, and every story must belong to exactly one phase (checked in main).
RELEASES = {
    "1.0.0": {
        "phases": [
            ("Skeleton", "Install the tool, get help in the terminal, save a profile, validate a capella.yaml and print a plan against the fake Capella harness",
             ["CAP-001", "CAP-002", "CAP-034", "CAP-003", "CAP-037", "CAP-004", "CAP-005", "CAP-006", "CAP-007", "CAP-008"]),
            ("Phase 1 — Project & cluster", "Answer the init wizard, then create, edit, protect and delete a project and cluster with its IP allowlist, idempotently",
             ["CAP-009", "CAP-039", "CAP-040", "CAP-010", "CAP-011", "CAP-035", "CAP-012", "CAP-038", "CAP-041", "CAP-049", "CAP-013", "CAP-014", "CAP-022"]),
            ("Phase 2 — Scale & hibernate", "Scale clusters out, in and up safely; power them off and on; run a weekly hibernation schedule",
             ["CAP-015", "CAP-016", "CAP-017", "CAP-018", "CAP-019", "CAP-020", "CAP-021"]),
            ("Phase 3 — Data model & access", "Buckets, scopes, collections and least-privilege database credentials, ready for applications",
             ["CAP-023", "CAP-024", "CAP-025", "CAP-026", "CAP-027", "CAP-046", "CAP-028", "CAP-029"]),
            ("Phase 4 — Adopt, harden & ship", "Import existing clusters with a no-change round trip, one-command build and teardown, drift reporting, nightly integration gate and customer docs",
             ["CAP-030", "CAP-036", "CAP-047", "CAP-048", "CAP-031", "CAP-042", "CAP-032", "CAP-044", "CAP-043", "CAP-045", "CAP-033", "CAP-050", "CAP-054", "CAP-055"]),
            ("Phase 5 — Custom cluster layouts", "Create a cluster with any size, disk type, multi-dimensional service layout and create option, and add or remove service groups later, from commands alone",
             ["CAP-051", "CAP-052", "CAP-053", "CAP-060"]),
            ("Phase 6 — Backup & restore", "Schedule cluster and bucket backups as code, list them, back up now and restore a cluster or a bucket, from commands alone",
             ["CAP-056", "CAP-057", "CAP-058", "CAP-059", "CAP-061"]),
        ],
        "checklist": [
            "All P0 stories are Implemented (and P1 stories are Implemented or explicitly descoped with sign-off)",
            "CI green on `main`: lint, type check, unit, contract and scenario suites",
            "CAP-032 nightly integration suite green three nights in a row against the sandbox organization, including the zero-writes re-run check",
            "Redaction canary test passes; no API key or password in any captured output (CAP-008)",
            "Every open question in the story files is answered or explicitly deferred to 1.1",
            "Import round trip (CAP-036 AC2) shows no changes against at least one real customer-like environment in the sandbox",
            "Time-to-first-environment check done by an engineer new to the tool against a real organization: under 60 minutes (release check; CAP-033 AC5 runs the same guide path against the fake in CI)",
            "The same time-to-first-environment check done once on a Windows laptop in Windows PowerShell, following the README's Windows install table (CAP-055)",
            "Source archive, wheel and SHA256SUMS built with `make dist` and attached to the GitHub Release (CAP-043); container image published; standalone executables for macOS, Linux and Windows in `downloads/` and listed in the README Download section (CAP-045); README, runbook and examples validated (CAP-033)",
            "A cluster backup and a bucket backup restored in the sandbox organization, and the restored data checked (CAP-057, CAP-059)",
            "`main` and `v*` tag rulesets active and `make rulesets-check` green before the repository is made public (CAP-050)",
        ],
    },
}


def render_phases(stories: list, phases: list) -> list:
    by_id = {s["id"]: s for s in stories}
    out = ["## Delivery phases", "",
           "Stories are delivered in phases; each phase ends with something an operator can run against Capella. "
           "Within a phase, follow the listed order (each story's **Depends on** column is authoritative).", "",
           "| Phase | Stories (in order) | Points | Done | Status | Outcome |", "|---|---|---|---|---|---|"]
    current_found = False
    for name, outcome, ids in phases:
        group = [by_id[i] for i in ids if by_id[i]["status"] != "Descoped"]
        done = [s for s in group if s["status"] == "Implemented"]
        cells = ", ".join(f"~~{s['id']}~~" if s["status"] == "Implemented" else s["id"] for s in group)
        if len(done) == len(group):
            status = "✅ Done"
        elif not current_found:
            status = "🚧 Current"
            current_found = True
        else:
            status = "⬜ Planned"
        out.append(f"| {name} | {cells} | {sum(s['points'] for s in group)} | "
                   f"{len(done)}/{len(group)} ({sum(s['points'] for s in done)} pts) | {status} | {outcome} |")
    out.append("")

    out += ["## Stories by phase", "",
            "Each phase lists its stories in delivery order.", ""]
    current_found = False
    for name, outcome, ids in phases:
        listed = [by_id[i] for i in ids]
        group = [s for s in listed if s["status"] != "Descoped"]
        done = [s for s in group if s["status"] == "Implemented"]
        if len(done) == len(group):
            badge = "✅ Done"
        elif not current_found:
            badge = "🚧 Current"
            current_found = True
        else:
            badge = "⬜ Planned"
        out += [f"### {name} — {badge} ({len(done)}/{len(group)} stories, "
                f"{sum(s['points'] for s in done)}/{sum(s['points'] for s in group)} points)", "",
                f"_{outcome}._", "",
                "| # | ID | Story | Priority | Epic | Points | Depends on | Status |", "|---|---|---|---|---|---|---|---|"]
        for n, st in enumerate(listed, 1):
            link = f"[{st['id']}]({st['file']})"
            cells = [link, st["title"], st["priority"], st["epic"], str(st["points"]), st["depends"]]
            if st["status"] == "Descoped":
                cells = [f"~~{c}~~" for c in cells]
                status = "🚫 Descoped"
            elif st["status"] == "Implemented":
                status = "✅ Implemented"
            elif st["status"] == "In progress":
                status = "🚧 In progress"
            else:
                status = "⬜ Not started"
            out.append(f"| {n} | " + " | ".join(cells + [status]) + " |")
        out.append("")
    return out


def parse_story(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    m = re.match(rf"#\s+({PREFIX}-\d{{3}})\s+—\s+(.+)", lines[0])
    if not m:
        raise ValueError(f"{path.name}: first line must be '# {PREFIX}-NNN — Title'")
    for i, line in enumerate(lines):
        if line.strip().startswith("| Epic | Priority | Points |"):
            cells = [c.strip() for c in lines[i + 2].strip().strip("|").split("|")]
            epic, priority, points, depends, status = cells
            if status not in STATUSES:
                raise ValueError(f"{path.name}: status '{status}' not in {STATUSES}")
            if priority not in PRIORITY_INFO:
                raise ValueError(f"{path.name}: priority '{priority}' not in {list(PRIORITY_INFO)}")
            return {"id": m.group(1), "title": m.group(2), "file": path.name, "epic": epic,
                    "priority": priority, "points": int(points), "depends": depends, "status": status}
    raise ValueError(f"{path.name}: header table not found")


def row(n: int, s: dict) -> str:
    link = f"[{s['id']}]({s['file']})"
    cells = [link, s["title"], s["epic"], str(s["points"])]
    if s["status"] == "Implemented":
        cells = [f"~~{c}~~" for c in cells]
        status = "✅ Implemented"
    elif s["status"] == "In progress":
        status = "🚧 In progress"
    else:
        status = "⬜ Not started"
    return f"| {n} | " + " | ".join(cells + [status]) + " |"


def pct(a: int, b: int) -> str:
    return f"{(100 * a / b):.0f}%" if b else "0%"


def render(release: str, every: list) -> str:
    cfg = RELEASES[release]
    prio = priority_info(release)
    stories = [s for s in every if s["status"] != "Descoped"]
    descoped = [s for s in every if s["status"] == "Descoped"]
    total_pts = sum(s["points"] for s in stories)
    by_status = {st: [s for s in stories if s["status"] == st] for st in STATUSES}
    done_pts = sum(s["points"] for s in by_status["Implemented"])

    out = [f"# Release {release} — Story Index", "",
           "> Generated by `scripts/update-story-index.py` from each story's header table. "
           "Don't edit this file by hand: change a story's **Status** (`Not started` → `In progress` → `Implemented`) "
           "and re-run `python3 scripts/update-story-index.py docs/release-" + release + "`. "
           "In the priority tables and the phase overview, implemented stories are ~~struck through~~.", "",
           "Architecture, domain model, conventions, NFRs and the global Definition of Done: "
           "[00-architecture.md](00-architecture.md).", "",
           "## Snapshot", "",
           "| Metric | Stories | Story points |", "|---|---|---|",
           f"| **Total** | **{len(stories)}** | **{total_pts}** |",
           f"| ✅ Implemented | {len(by_status['Implemented'])} | {done_pts} |",
           f"| 🚧 In progress | {len(by_status['In progress'])} | {sum(s['points'] for s in by_status['In progress'])} |",
           f"| ⬜ Not started | {len(by_status['Not started'])} | {sum(s['points'] for s in by_status['Not started'])} |",
           f"| Not yet implemented (in progress + not started) | {len(stories) - len(by_status['Implemented'])} | {total_pts - done_pts} |",
           f"| **Completion** | {pct(len(by_status['Implemented']), len(stories))} | {pct(done_pts, total_pts)} |"]
    if descoped:
        out.append(f"| 🚫 Descoped (not counted above) | {len(descoped)} | {sum(s['points'] for s in descoped)} |")
    out.append("")

    out += ["### By priority", "", "| Priority | Meaning | Stories | Points | Implemented (stories / points) |",
            "|---|---|---|---|---|"]
    for p, meaning in prio.items():
        group = [s for s in stories if s["priority"] == p]
        if not group:
            continue
        done = [s for s in group if s["status"] == "Implemented"]
        out.append(f"| {p} | {meaning} | {len(group)} | {sum(s['points'] for s in group)} | "
                   f"{len(done)} / {sum(s['points'] for s in done)} |")
    out.append("")

    epics = OrderedDict()
    for s in stories:
        epics.setdefault(s["epic"], []).append(s)
    out += ["### By epic", "", "| Epic | Stories | Points | Implemented (stories / points) |", "|---|---|---|---|"]
    for e, group in epics.items():
        done = [s for s in group if s["status"] == "Implemented"]
        out.append(f"| {e} | {len(group)} | {sum(s['points'] for s in group)} | "
                   f"{len(done)} / {sum(s['points'] for s in done)} |")
    out.append("")

    out += ["## Stories by priority", ""]
    for p, meaning in prio.items():
        group = [s for s in stories if s["priority"] == p]
        if not group:
            continue
        out += [f"### {p} — {meaning} ({len(group)} stories, {sum(s['points'] for s in group)} points)", "",
                "| # | ID | Story | Epic | Points | Status |", "|---|---|---|---|---|---|"]
        out += [row(n, s) for n, s in enumerate(group, 1)]
        out.append("")

    out += render_phases(every, cfg["phases"])
    if descoped:
        out += ["## Descoped", "", "Kept for reference; not counted in any total. Each story file says why.", "",
                "| ID | Story | Epic | Points |", "|---|---|---|---|"]
        out += [f"| [{s['id']}]({s['file']}) | {s['title']} | {s['epic']} | {s['points']} |" for s in descoped]
        out.append("")
    out += ["## Release checklist", ""] + [f"- [ ] {item}" for item in cfg["checklist"]] + [""]
    return "\n".join(out)


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--check"]
    check = "--check" in sys.argv[1:]
    release_dir = Path(args[0] if args else "docs/release-1.0.0")
    stories = sorted((parse_story(p) for p in release_dir.glob(f"{PREFIX}-*.md")), key=lambda s: s["id"])
    ids = [int(s["id"].split("-")[1]) for s in stories]
    if not ids or ids != list(range(ids[0], ids[0] + len(ids))):
        sys.exit(f"story numbering has gaps or duplicates: {ids}")
    release = release_dir.name.removeprefix("release-")
    if release not in RELEASES:
        sys.exit(f"no phase configuration for release {release}; add it to RELEASES")
    phased = [i for _, _, ids in RELEASES[release]["phases"] for i in ids]
    if sorted(phased) != [s["id"] for s in stories]:
        sys.exit(f"every story must be in exactly one phase; check RELEASES: {sorted(set(s['id'] for s in stories) ^ set(phased))}")
    rendered = render(release, stories)
    index = release_dir / "README.md"
    if check:
        current = index.read_text(encoding="utf-8") if index.exists() else ""
        if current != rendered:
            sys.exit(f"out of date with the story files: {index}; "
                     f"run: python3 scripts/update-story-index.py {release_dir}")
        print(f"{index} is up to date")
        return
    index.write_text(rendered, encoding="utf-8")
    live = [s for s in stories if s["status"] != "Descoped"]
    print(f"README.md updated: {len(live)} stories, {sum(s['points'] for s in live)} points"
          + (f" ({len(stories) - len(live)} descoped)" if len(live) < len(stories) else ""))


if __name__ == "__main__":
    main()
