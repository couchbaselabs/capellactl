"""capellactl sync: refresh capella.yaml from Capella (CAP-038). Read-only towards Capella."""

from __future__ import annotations

import difflib
from typing import Any

import click
import yaml

from capellactl.api import endpoints as ep
from capellactl.cli.console import err, out
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.state import AppState


def _comparable(data: Any) -> Any:
    """Drop tool comments and key order noise so only real differences count."""
    if isinstance(data, dict):
        return {k: _comparable(v) for k, v in data.items() if not str(k).startswith("__")}
    if isinstance(data, list):
        return [_comparable(v) for v in data]
    return data


def _renamed_project(client: Any, capella_projects: list[dict[str, Any]], entries: list[Any],
                     entry: Any) -> list[dict[str, Any]]:
    """The one Capella project, not in the file, that holds a cluster declared under `entry` (CAP-048 AC5)."""
    declared = {str(c.get("name")) for c in entry.clusters if isinstance(c, dict)}
    in_file = {e.name for e in entries}
    if not declared:
        return []
    found = [p for p in capella_projects if p.get("name") not in in_file
             and any(c.get("name") in declared for c in ep.list_clusters(client, str(p["id"])))]
    return found if len(found) == 1 else []


def _was_deployed(entry: Any) -> bool:
    """True when the project or one of its clusters carries an id, i.e. it existed in Capella once."""
    return bool(entry.data.get("id")) or any(isinstance(c, dict) and c.get("id") for c in entry.clusters)


def _carry_over_project(prev: dict[str, Any] | None, res: Any) -> list[str]:
    """Keep values that exist only locally for one project (Capella never returns them)."""
    kept: list[str] = []
    if not prev:
        return kept
    old_clusters = {c.get("name"): c for c in prev.get("clusters") or [] if isinstance(c, dict)}
    for cl in res.data.get("clusters") or []:
        old = old_clusters.get(cl.get("name"))
        if not old:
            continue
        if old.get("allowAnyIp"):
            cl["allowAnyIp"] = True
        old_pw = {u.get("name"): u.get("password") for u in old.get("databaseCredentials") or []
                  if isinstance(u, dict) and u.get("password")}
        for u in cl.get("databaseCredentials") or []:
            if u.get("name") in old_pw:
                rest = {k: u.pop(k) for k in list(u) if k not in ("name",) and not str(k).startswith("__")}
                u.update({"password": old_pw[u["name"]], **rest})  # right after the name, as import writes it
                for k in [k for k in u if str(k).startswith("__comment_")]:
                    res.comments[k] = ("password reference kept from the previous capella.yaml "
                                       "(Capella never returns passwords)")
                kept.append(f"password reference for {cl['name']}/{u['name']}")
    return kept


@click.command("sync", epilog="\b\nExamples:\n  capellactl sync\n  capellactl sync --dry-run      "
                              "(CI: exit 2 when capella.yaml is out of date)\n  capellactl sync --project non-prod\n"
                              "  capellactl sync --cluster nova-dev-01")
@click.option("--project", "projects", multiple=True, metavar="NAME", help="Only these projects (repeatable).")
@click.option("--cluster", "clusters", multiple=True, metavar="NAME", help="Only these clusters (repeatable).")
@click.option("--dry-run", is_flag=True, help="Show the difference without writing; exit 2 when out of sync.")
@click.option("--full", is_flag=True, help="Write every field, including values equal to the defaults.")
@click.pass_obj
def sync(state: AppState, projects: tuple[str, ...], clusters: tuple[str, ...], dry_run: bool, full: bool) -> None:
    """Refresh capella.yaml from Capella for every project it describes (shows what changed)."""
    from capellactl.config.loader import project_entries
    from capellactl.importer import (
        NEW_CLUSTER_TEMPLATE,
        NO_PROJECTS_TEMPLATE,
        ImportResult,
        build_document,
        combine,
        render,
        to_projects_form,
    )

    path = state.config_path()
    if not path.exists():
        raise CliExit(ExitCode.CONFIG_INVALID, f"{path} not found; run 'capellactl import' first",
                      topic="getting-started")
    old_text = path.read_text(encoding="utf-8")
    try:
        old = yaml.safe_load(old_text) or {}
    except yaml.YAMLError as exc:
        raise CliExit(ExitCode.CONFIG_INVALID, f"{path} is not valid YAML ({exc}); re-create it with "
                                               "'capellactl import --force'") from None
    entries = project_entries(old)
    unknown = [n for n in projects if n not in {e.name for e in entries}]
    if unknown:
        raise CliExit(ExitCode.CONFIG_INVALID, f"not in {path.name}: {', '.join(unknown)} "
                                               "(add them with 'capellactl import --project NAME')")
    org = old.get("organizationId")
    client = state.client(org if isinstance(org, str) and not org.startswith("${") else None)
    capella_projects = ep.list_projects(client)

    results: list[Any] = []
    kept: list[str] = []
    seen_clusters: set[str] = set()
    warnings: list[str] = []
    for e in entries:
        prev = {**e.data, "clusters": e.clusters}
        refresh = not projects or e.name in projects
        pinned = e.data.get("id")
        match = [p for p in capella_projects if (p.get("id") == pinned if pinned else p.get("name") == e.name)]
        if refresh and not match and not pinned:
            match = _renamed_project(client, capella_projects, entries, e)
            if match:
                warnings.append(f"project {e.name} was renamed in Capella to {match[0].get('name')}; "
                                f"{path.name} now uses the new name and its id")
        if refresh and len(match) > 1:
            raise CliExit(ExitCode.BLOCKED, f"{len(match)} projects are named {e.name}; add id: to it with "
                                            "'capellactl import --force'", topic="idempotency")
        if refresh and not match and _was_deployed(e):
            warnings.append(f"project {e.name} no longer exists in Capella; removed from {path.name} with its "
                            f"clusters and everything in them")
            continue
        if not refresh or not match:
            if refresh:
                warnings.append(f"project {e.name} is not in Capella yet; kept as it is in {path.name} "
                                "(deploy it with 'capellactl apply')")
            results.append(ImportResult(data={"project": {k: v for k, v in e.data.items() if k != "clusters"},
                                              "clusters": list(e.clusters)}))
            continue
        proj = match[0]
        found = ep.list_clusters(client, str(proj["id"]))
        chosen = [c for c in found if not clusters or c.get("name") in clusters]
        seen_clusters.update(str(c.get("name")) for c in chosen)
        recorded = {(str(c.get("name")), str(u.get("name"))): (u.get("access"), u.get("password"))
                    for c in e.clusters if isinstance(c, dict)
                    for u in c.get("databaseCredentials") or [] if isinstance(u, dict) and u.get("access")}

        def known(cl: str, cr: str, rec: dict[tuple[str, str], tuple[Any, Any]] = recorded) -> tuple[Any, Any] | None:
            return rec.get((cl, cr))

        res = build_document(client, proj, chosen, full=full, all_clusters=found, known_access=known)
        if pinned:
            res.data["project"] = {"id": pinned, **res.data["project"]}
        kept += _carry_over_project(prev, res)
        if clusters:  # refresh only the named clusters; keep the others as they are
            refreshed = {c.get("name") for c in res.data["clusters"]}
            gone = {str(c.get("name")) for c in e.clusters if c.get("id") and c.get("name") in clusters
                    and c.get("name") not in refreshed}
            seen_clusters.update(gone)
            warnings += [f"cluster {n} no longer exists in Capella; removed from {path.name} with its buckets, "
                         "credentials and other settings" for n in sorted(gone)]
            res.data["clusters"] = [c for c in e.clusters if c.get("name") not in refreshed | gone] + res.data["clusters"]
        else:
            live = {c.get("name") for c in res.data["clusters"]}
            warnings += [f"cluster {c.get('name')} no longer exists in Capella; removed from {path.name} with its "
                         "buckets, credentials and other settings"
                         for c in e.clusters if isinstance(c, dict) and c.get("id") and c.get("name") not in live]
        results.append(res)
    missing = [n for n in clusters if n not in seen_clusters]
    if missing:
        raise CliExit(ExitCode.ERROR, f"cluster(s) not found in Capella: {', '.join(missing)}")

    combined = combine(results, client.org_id)
    if isinstance(org, str) and org.startswith("${"):
        combined.data["organizationId"] = org
    if old.get("credentialsOutput"):
        combined.data["credentialsOutput"] = old["credentialsOutput"]
    try:
        org_name = ep.get_organization(client)[0].get("name")
    except Exception:  # noqa: BLE001 - only used in a comment
        org_name = None
    new_text = render(combined, org_name)
    if "projects: []" in new_text:
        new_text = new_text.replace("projects: []\n", "projects: []\n" + NO_PROJECTS_TEMPLATE, 1)
    if "clusters: []" in new_text:
        new_text = new_text.replace("clusters: []\n", "clusters: []\n" + NEW_CLUSTER_TEMPLATE, 1)

    before = _comparable(to_projects_form(old))
    after = _comparable(yaml.safe_load(new_text))
    for w in warnings + [w for w in combined.warnings if w not in warnings]:
        err(f"warning: {w}")
    if before == after:
        out(f"{path.name} is already in sync with Capella.")
        return
    a = yaml.safe_dump(before, sort_keys=False, width=120).splitlines()
    b = yaml.safe_dump(after, sort_keys=False, width=120).splitlines()
    diff = list(difflib.unified_diff(a, b, f"{path.name} (now)", f"{path.name} (from Capella)", lineterm="", n=2))
    out("\n".join(diff))
    if dry_run:
        raise CliExit(ExitCode.CHANGES, f"{path.name} is out of sync with Capella (nothing written; run "
                                        "'capellactl sync' to update it)")
    backup = path.with_name(path.name + ".bak")
    backup.write_text(old_text, encoding="utf-8")
    path.write_text(new_text, encoding="utf-8")
    for k in kept:
        err(f"kept {k}")
    out(f"{path.name} updated from Capella (previous version kept as {backup.name}).")
