"""capellactl sync: refresh capella.yaml from Capella (CAP-038). Read-only towards Capella."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

import click
import yaml

from capellactl.api import endpoints as ep
from capellactl.cli.console import err, out, warning
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.state import AppState
from capellactl.output.notice import Notice

GONE = ("None needed if it was deleted on purpose; otherwise restore {file} from {file}.bak and run 'capellactl apply' "
        "to create it again.")


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


UNREAD_LABELS = {"allowedCidrs": "allowed CIDRs", "buckets": "buckets, scopes and collections",
                 "databaseCredentials": "database credentials", "hibernation": "hibernation schedule",
                 "backupSchedule": "backup schedule"}


def _keep_unread(prev: dict[str, Any] | None, res: Any, file_name: str) -> None:
    """Keep what Capella could not return now (a powered-off cluster, or a read error) from the previous file.

    Dropping it would remove buckets and credentials that still exist from the file, and `apply --prune` would then
    delete them in Capella. The next sync that can read them refreshes them."""
    if not prev or not res.unread:
        return
    old_clusters = [c for c in prev.get("clusters") or [] if isinstance(c, dict)]
    for cl in res.data.get("clusters") or []:
        info = res.unread.get(str(cl.get("id")))
        if not info:
            continue
        old = (next((c for c in old_clusters if c.get("id") and c.get("id") == cl.get("id")), None)
               or next((c for c in old_clusters if not c.get("id") and c.get("name") == cl.get("name")), None))
        if old is None:
            continue
        kept: list[str] = []
        moved: dict[str, Any] = {}
        unkept = False
        for f in info["fields"]:
            if f.startswith(("scopes:", "bucketBackup:")):
                part, bucket = f.split(":", 1)
                field_ = "scopes" if part == "scopes" else "backupSchedule"
                ob = next((b for b in old.get("buckets") or [] if isinstance(b, dict) and b.get("name") == bucket), None)
                nb = next((b for b in cl.get("buckets") or [] if b.get("name") == bucket), None)
                if ob and ob.get(field_) and nb is not None:
                    if field_ == "backupSchedule":  # before the scopes
                        scopes_ = nb.pop("scopes", None)
                        nb[field_] = ob[field_]
                        if scopes_ is not None:
                            nb["scopes"] = scopes_
                    else:
                        nb[field_] = ob[field_]
                    kept.append(f"{'scopes' if part == 'scopes' else 'backup schedule'} of bucket {bucket}")
            elif old.get(f):
                moved[f] = old[f]
                kept.append(UNREAD_LABELS[f])
            elif f != "backupSchedule":  # no schedule in the file: nothing to keep, nothing lost
                unkept = True
        if not kept:
            continue
        info["kept"] = True
        if not unkept:  # everything that was not read is kept: replace the "not imported" notes and warnings
            for k in [k for k in cl if str(k).startswith("__comment_") and str(cl[k]).startswith("not imported:")]:
                del cl[k]
            res.warnings[:] = [w for w in res.warnings
                               if not (w.what.startswith(f"cluster {info['name']}: ") and " not imported (" in w.what)]
        cl[f"__comment_kept_{cl.get('id')}__"] = (f"kept from the previous {file_name}: {', '.join(kept)}\n"
                                                  f"(not readable now: {info['reason']}; the next sync refreshes them)")
        for f, v in moved.items():
            cl.pop(f, None)
            cl[f] = v
        res.warnings.append(Notice(f"cluster {info['name']}: {', '.join(kept)} kept from {file_name} "
                                   f"({info['reason']})", "Run 'capellactl sync' again when the cluster is on to "
                                                          "refresh them."))


def _is_capellactl_file(path: Path) -> bool:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return False
    return isinstance(raw, dict) and ("projects" in raw or "project" in raw)


def sync_or_create(state: AppState, path: Path, projects: tuple[str, ...] = (), project_ids: tuple[str, ...] = (),
                   clusters: tuple[str, ...] = (), cluster_ids: tuple[str, ...] = (), skip: tuple[str, ...] = (),
                   dry_run: bool = False, to_stdout: bool = False, full: bool = False, force: bool = False) -> None:
    """One command for capella.yaml (CAP-054): create it when there is none, otherwise bring it in line with Capella."""
    if path.exists() and not force and _is_capellactl_file(path):
        from capellactl.config.loader import declared_org_id

        file_org, key_org = declared_org_id(path, state.env), state.client().org_id
        if file_org and key_org and file_org != key_org:  # never mix two organizations (CAP-047)
            if not to_stdout:
                raise CliExit(ExitCode.CONFIG_INVALID,
                              f"{path} is for organization {file_org}, not {key_org}; nothing was written",
                              action=f"Pass --force to rewrite it for {key_org} (the current file is kept as "
                                     f"{path.name}.bak), or --file PATH to write a separate file.")
            from capellactl.cli.env import run_import

            run_import(state, None, projects, None, clusters, cluster_ids, str(path), full, True, False)
            return
        run_sync(state, path, projects, project_ids, clusters, cluster_ids, skip, dry_run, to_stdout, full)
        return
    if dry_run:
        raise CliExit(ExitCode.CHANGES, f"{path.name} does not exist yet",
                                        action="Run 'capellactl sync' to write it from Capella.")
    from capellactl.cli.env import run_import

    client = state.client()
    names = list(projects)
    if skip or len(project_ids) > 1:
        listed = ep.list_projects(client)
        names += [str(p.get("name")) for p in listed if p.get("id") in project_ids]
        if skip and not names:
            names = [str(p.get("name")) for p in listed if p.get("name") not in skip]
    single_id = project_ids[0] if len(project_ids) == 1 and not projects else None
    run_import(state, client, tuple(n for n in names if n not in skip), single_id, clusters, cluster_ids, str(path),
               full, to_stdout, force)
    if skip and not to_stdout and path.exists():
        from capellactl.config.editor import ConfigEditor

        ed = ConfigEditor(path)
        ed.doc.insert(list(ed.doc.keys()).index("projects") if "projects" in ed.doc else len(ed.doc),
                      "skipProjects", sorted(set(skip)))
        path.write_text(ed.text(), encoding="utf-8")


@click.command("sync", epilog="\b\nExamples:\n  capellactl sync                       (every project of the organization)\n"
                              "  capellactl sync --dry-run             (CI: exit 2 when capella.yaml is out of date)\n"
                              "  capellactl sync --project non-prod    (only this project; added when it is new)\n"
                              "  capellactl sync --skip-project sandbox  (leave it out from now on)\n"
                              "  capellactl sync --cluster nova-dev-01\n"
                              "  capellactl sync --project nova-dev --stdout > nova-dev.yaml")
@click.option("--project", "projects", multiple=True, metavar="NAME",
              help="Only these projects (repeatable; added when not in capella.yaml).")
@click.option("--project-id", "project_ids", multiple=True, metavar="ID",
              help="Only these project IDs (repeatable), when several projects share a name.")
@click.option("--cluster", "clusters", multiple=True, metavar="NAME", help="Only these clusters (repeatable).")
@click.option("--cluster-id", "cluster_ids", multiple=True, metavar="ID", help="Only these cluster IDs (repeatable).")
@click.option("--skip-project", "skip", multiple=True, metavar="NAME",
              help="Leave this project out now and on later syncs (recorded in capella.yaml; repeatable).")
@click.option("--dry-run", is_flag=True, help="Show the difference without writing; exit 2 when out of sync.")
@click.option("--stdout", "to_stdout", is_flag=True, help="Print the YAML instead of writing the file.")
@click.option("--full", is_flag=True, help="Write every field, including values equal to the defaults.")
@click.option("--force", is_flag=True, help="Replace a file that is not a capellactl file (a .bak is kept).")
@click.pass_obj
def sync(state: AppState, projects: tuple[str, ...], project_ids: tuple[str, ...], clusters: tuple[str, ...],
         cluster_ids: tuple[str, ...], skip: tuple[str, ...], dry_run: bool, to_stdout: bool, full: bool,
         force: bool) -> None:
    """Bring capella.yaml in line with Capella: writes it when there is none, refreshes every project and adds the
    organization's projects that are missing (read-only towards Capella)."""
    sync_or_create(state, state.config_path(), projects, project_ids, clusters, cluster_ids, skip, dry_run, to_stdout,
                   full, force)


def run_sync(state: AppState, path: Path, projects: tuple[str, ...], project_ids: tuple[str, ...],
             clusters: tuple[str, ...], cluster_ids: tuple[str, ...], skip: tuple[str, ...], dry_run: bool,
             to_stdout: bool, full: bool) -> None:
    from capellactl.config.loader import project_entries
    from capellactl.importer import (
        NEW_CLUSTER_TEMPLATE,
        NO_PROJECTS_TEMPLATE,
        POWERED_OFF,
        ImportResult,
        build_document,
        combine,
        render,
        to_projects_form,
    )

    old_text = path.read_text(encoding="utf-8")
    old = yaml.safe_load(old_text) or {}
    entries = project_entries(old)
    org = old.get("organizationId")
    client = state.client(org if isinstance(org, str) and not org.startswith("${") else None)
    capella_projects = ep.list_projects(client)
    in_file = {e.name for e in entries}
    in_capella = {str(p.get("name")) for p in capella_projects}
    unknown = [n for n in projects if n not in in_file and n not in in_capella]
    unknown += [i for i in project_ids if not any(p.get("id") == i for p in capella_projects)]
    if unknown:
        raise CliExit(ExitCode.CONFIG_INVALID, f"not in {path.name} or in Capella: {', '.join(unknown)}",
                                               action="Check the names with 'capellactl project list', then run the "
                                                      "command again.")
    # --project NAME brings a skipped project back; --skip-project NAME leaves it out from now on (CAP-054 AC3)
    skipped = [n for n in old.get("skipProjects") or [] if n not in projects] + \
              [n for n in skip if n not in (old.get("skipProjects") or [])]
    named = set(projects) | {str(p.get("name")) for p in capella_projects if p.get("id") in project_ids}
    cluster_filter = bool(clusters or cluster_ids)

    results: list[Any] = []
    kept: list[str] = []
    seen_clusters: set[str] = set()
    covered: set[str] = set()
    warnings: list[Notice] = []
    refreshed: list[tuple[str, int]] = []
    for e in entries:
        if e.name in skipped:
            warnings.append(Notice(f"project {e.name} removed from {path.name} and skipped from now on",
                                   f"None needed. Run 'capellactl sync --project {e.name}' to add it back."))
            continue
        prev = {**e.data, "clusters": e.clusters}
        refresh = not named or e.name in named
        pinned = e.data.get("id")
        match = [p for p in capella_projects if (p.get("id") == pinned if pinned else p.get("name") == e.name)]
        if refresh and not match and not pinned:
            match = _renamed_project(client, capella_projects, entries, e)
            if match:
                warnings.append(Notice(f"project {e.name} was renamed in Capella to {match[0].get('name')}; "
                                       f"{path.name} now uses the new name and its id",
                                       f"Use --project {match[0].get('name')} in your commands and scripts from now on."))
        covered.update(str(p.get("id")) for p in match)
        if refresh and len(match) > 1:
            raise CliExit(ExitCode.BLOCKED, f"{len(match)} projects are named {e.name}, so capellactl cannot tell "
                                            f"which one {path.name} means", topic="idempotency",
                                            action=f"Run 'capellactl sync --force' to rewrite the file from Capella "
                                                   f"with each one's id (the current file is kept as "
                                                   f"{path.name}.bak).")
        if refresh and not match and _was_deployed(e):
            warnings.append(Notice(f"project {e.name} no longer exists in Capella; removed from {path.name} with "
                                   "its clusters and everything in them",
                                   f"None needed if it was deleted on purpose; otherwise restore {path.name} from "
                                   f"{path.name}.bak and run 'capellactl apply' to create it again."))
            continue
        if not refresh or not match:
            if refresh:
                warnings.append(Notice(f"project {e.name} is not in Capella yet; kept as it is in {path.name}",
                                       "Run 'capellactl apply' to create it."))
            results.append(ImportResult(data={"project": {k: v for k, v in e.data.items() if k != "clusters"},
                                              "clusters": list(e.clusters)}))
            continue
        proj = match[0]
        found = ep.list_clusters(client, str(proj["id"]))
        chosen = [c for c in found if not cluster_filter or c.get("name") in clusters or c.get("id") in cluster_ids]
        seen_clusters.update(str(c.get("name")) for c in chosen)
        seen_clusters.update(str(c.get("id")) for c in chosen)
        recorded = {(str(c.get("name")), str(u.get("name"))): (u.get("access"), u.get("password"))
                    for c in e.clusters if isinstance(c, dict)
                    for u in c.get("databaseCredentials") or [] if isinstance(u, dict) and u.get("access")}

        def known(cl: str, cr: str, rec: dict[tuple[str, str], tuple[Any, Any]] = recorded) -> tuple[Any, Any] | None:
            return rec.get((cl, cr))

        res = build_document(client, proj, chosen, full=full, all_clusters=found, known_access=known)
        if pinned:
            res.data["project"] = {"id": pinned, **res.data["project"]}
        kept += _carry_over_project(prev, res)
        _keep_unread(prev, res, path.name)
        if cluster_filter:  # refresh only the named clusters; keep the others as they are
            done = {c.get("name") for c in res.data["clusters"]}
            gone = {str(c.get("name")) for c in e.clusters if c.get("id") and (c.get("name") in clusters
                                                                              or c.get("id") in cluster_ids)
                    and c.get("name") not in done}
            seen_clusters.update(gone)
            warnings += [Notice(f"cluster {n} no longer exists in Capella; removed from {path.name} with its "
                                "buckets, credentials and other settings", GONE.format(file=path.name))
                         for n in sorted(gone)]
            res.data["clusters"] = [c for c in e.clusters if c.get("name") not in done | gone] + res.data["clusters"]
        else:
            live = {c.get("name") for c in res.data["clusters"]}
            warnings += [Notice(f"cluster {c.get('name')} no longer exists in Capella; removed from {path.name} "
                                "with its buckets, credentials and other settings", GONE.format(file=path.name))
                         for c in e.clusters if isinstance(c, dict) and c.get("id") and c.get("name") not in live]
            refreshed.append((str(proj.get("name")), len(found)))
        results.append(res)

    # Projects of the organization that capella.yaml does not describe yet (CAP-054 AC1)
    added: list[tuple[str, int]] = []
    for proj in capella_projects:
        name = str(proj.get("name"))
        if str(proj.get("id")) in covered or name in in_file or name in skipped:
            continue
        if (named and name not in named) or (cluster_filter and not named):
            continue
        found = ep.list_clusters(client, str(proj["id"]))
        chosen = [c for c in found if not cluster_filter or c.get("name") in clusters or c.get("id") in cluster_ids]
        seen_clusters.update(str(c.get("name")) for c in chosen)
        seen_clusters.update(str(c.get("id")) for c in chosen)
        results.append(build_document(client, proj, chosen, full=full, all_clusters=found))
        added.append((name, len(chosen)))
    missing = [n for n in (*clusters, *cluster_ids) if n not in seen_clusters]
    if missing:
        raise CliExit(ExitCode.ERROR, f"cluster(s) not found in Capella: {', '.join(missing)}",
                                      action="Check the names with 'capellactl cluster list', then run the command "
                                             "again.")

    combined = combine(results, client.org_id)
    if isinstance(org, str) and org.startswith("${"):
        combined.data["organizationId"] = org
    top: dict[str, Any] = {k: combined.data[k] for k in ("apiVersion", "organizationId") if k in combined.data}
    if old.get("credentialsOutput"):
        top["credentialsOutput"] = old["credentialsOutput"]
    if skipped:
        top["skipProjects"] = skipped
    combined.data = {**top, **{k: v for k, v in combined.data.items() if k not in top}}
    try:
        org_name = ep.get_organization(client)[0].get("name")
    except Exception:  # noqa: BLE001 - only used in a comment
        org_name = None
    new_text = render(combined, org_name)
    if "projects: []" in new_text:
        new_text = new_text.replace("projects: []\n", "projects: []\n" + NO_PROJECTS_TEMPLATE, 1)
    if "clusters: []" in new_text:
        new_text = new_text.replace("clusters: []\n", "clusters: []\n" + NEW_CLUSTER_TEMPLATE, 1)
    if to_stdout:
        out(new_text.rstrip("\n"))
        return

    for w in warnings + [w for w in combined.warnings if w not in warnings]:
        warning(w)
    for name, n in added:
        out(f"added project {name} ({n} cluster{'s' if n != 1 else ''})")
    off = [(info["name"], bool(info.get("kept"))) for r in results for info in getattr(r, "unread", {}).values()
           if info["reason"] in POWERED_OFF]
    if off:
        out(f"{len(off)} cluster{'s are' if len(off) != 1 else ' is'} turned off: {', '.join(n for n, _ in off)}")
        if any(k for _, k in off):
            out(f"  kept from {path.name}: buckets and credentials of "
                f"{', '.join(n for n, k in off if k)} (refreshed when they are on)")
        if any(not k for _, k in off):
            out(f"  not read yet: buckets and credentials of {', '.join(n for n, k in off if not k)} "
                "— run 'capellactl sync' again when they are on")

    before = _comparable(to_projects_form(old))
    after = _comparable(yaml.safe_load(new_text))
    if before == after:
        n_projects = len(combined.data.get("projects") or [])
        n_clusters = sum(len(p.get("clusters") or []) for p in combined.data.get("projects") or [])
        scope = f" for {', '.join(sorted(named))} (other projects not checked)" if named else ""
        out(f"{path.name} is already in sync with Capella{scope}: {n_projects} project{'s' if n_projects != 1 else ''}, "
            f"{n_clusters} cluster{'s' if n_clusters != 1 else ''}"
            + (f"; skipped: {', '.join(skipped)}" if skipped else "") + ".")
        return
    a = yaml.safe_dump(before, sort_keys=False, width=120).splitlines()
    b = yaml.safe_dump(after, sort_keys=False, width=120).splitlines()
    diff = list(difflib.unified_diff(a, b, f"{path.name} (now)", f"{path.name} (from Capella)", lineterm="", n=2))
    out("\n".join(diff))
    if dry_run:
        raise CliExit(ExitCode.CHANGES, f"{path.name} is out of sync with Capella; nothing was written",
                                        action="Run 'capellactl sync' to update it.")
    backup = path.with_name(path.name + ".bak")
    backup.write_text(old_text, encoding="utf-8")
    path.write_text(new_text, encoding="utf-8")
    for k in kept:
        err(f"kept {k}")
    out(f"{path.name} updated from Capella (previous version kept as {backup.name}).")
