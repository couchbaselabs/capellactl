"""Whole-environment commands: validate (CAP-002), plan (CAP-005), apply (CAP-006)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click

from capellactl.api import endpoints as ep
from capellactl.api.errors import Forbidden, ServerError
from capellactl.cli import console
from capellactl.cli.console import err, out
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.state import AppState
from capellactl.engine.clock import format_duration
from capellactl.engine.executor import ApplyResult, execute
from capellactl.engine.planner import build_plan
from capellactl.engine.waiter import WaitTimeout
from capellactl.output.render import dumps, render_plan_json, render_plan_text, render_summary_table
from capellactl.resources import build_tree
from capellactl.resources.base import ActionType, Plan, PlanError, Reconciler

pass_state = click.make_pass_decorator(AppState)

# Tests replace this to plug in stub reconcilers for kinds that later stories implement.
TREE_FACTORY = build_tree


def not_yet(story: str, what: str) -> CliExit:
    return CliExit(ExitCode.ERROR, f"{what} is not available in this build yet (planned in {story}; see "
                                   "docs/release-1.0.0/INDEX.md)")


# ------------------------------------------------------------------ helpers
def make_plan(state: AppState, targets: list[str] | None = None, descendants: bool = True,
              prune: bool = False, rotate_passwords: bool = False, all_unmanaged: bool = False,
              **options: bool) -> tuple[Plan, Any, Any]:
    """`options`: RunContext switches such as power_on, allow_service_removal, skip_capacity_check."""
    cfg = state.load_config()
    client = state.client(cfg.organization_id)
    ctx = state.run_context(client, cfg)
    ctx.rotate_passwords = rotate_passwords
    for k, v in options.items():
        setattr(ctx, k, v)
    tree: Reconciler = TREE_FACTORY()
    try:
        plan = build_plan(ctx, cfg, tree, targets, descendants, prune, all_unmanaged)
    except PlanError as exc:
        raise CliExit(ExitCode.ERROR, str(exc)) from None
    except ValueError as exc:
        raise CliExit(ExitCode.CONFIG_INVALID, str(exc)) from None
    return plan, cfg, ctx


def plan_header(cfg: Any, client: Any) -> str:
    names = cfg.project_names()
    label = f"Project {names[0]}" if len(names) == 1 else f"Projects {', '.join(names)}"
    return f"{label} · organization {client.org_id}"


def projects_label(cfg: Any) -> str:
    names = cfg.project_names()
    return f"project {names[0]}" if len(names) == 1 else f"projects {', '.join(names)}"


# ----------------------------------------------------------------- validate
@click.command(epilog="\b\nExamples:\n  capellactl validate\n  capellactl -c prod.yaml validate")
@pass_state
def validate(state: AppState) -> None:
    """Validate the config file offline (schema, references, secrets). No API calls."""
    cfg = state.load_config()
    if state.json:
        out(dumps({"valid": True, "file": str(cfg.path), "counts": cfg.counts()}))
    else:
        out(cfg.summary())


# --------------------------------------------------------------------- plan
@click.command(epilog="\b\nExamples:\n  capellactl plan\n  capellactl plan --target cluster/nova-dev-01\n"
                      "  capellactl -o json plan --detailed-exitcode")
@click.option("--target", "targets", multiple=True, metavar="KIND/NAME", help="Limit to these resources (repeatable).")
@click.option("--detailed-exitcode", is_flag=True, help="Exit 2 when there are changes, 0 when none.")
@pass_state
def plan(state: AppState, targets: tuple[str, ...], detailed_exitcode: bool) -> None:
    """Show what apply would change. Read-only: makes only GET requests."""
    p, cfg, ctx = make_plan(state, list(targets) or None)
    if state.json:
        out(dumps(render_plan_json(p)))
    else:
        out(render_plan_text(p, plan_header(cfg, ctx.client)))
    if p.blocked:
        raise CliExit(ExitCode.BLOCKED, "")
    if detailed_exitcode and p.has_changes:
        raise CliExit(ExitCode.CHANGES, "")


# -------------------------------------------------------------------- apply
def confirm_data_delete(ctx: Any, action: Any) -> bool:
    """Show what a bucket, scope or collection delete loses and ask for its name to be typed (CAP-024 AC1/AC3,
    CAP-026 AC4/AC5)."""
    from capellactl.resources import bucket as bucket_res
    from capellactl.resources import scope as scope_res

    bucket = action if action.kind == "bucket" else action.ancestor("bucket")
    cluster = bucket.parent if bucket is not None else None
    project = cluster.ancestor("project") if cluster is not None else None
    assert bucket is not None and cluster is not None and project is not None and bucket.id is not None
    if action.kind == "bucket":
        getter = ep.get_free_bucket if cluster.data.get("free") else ep.get_bucket
        body, _ = getter(ctx.client, project.id, cluster.id, bucket.id)
        lines = bucket_res.delete_details(ctx.client, project.id, cluster.id, body)
    else:
        scope = action if action.kind == "scope" else action.parent
        coll = str(action.desired["name"]) if action.kind == "collection" else None
        lines = scope_res.delete_details(ctx.client, project.id, cluster.id, str(bucket.desired["name"]), bucket.id,
                                         str(scope.desired["name"]), coll)
    for line in lines:
        out(f"  {line}")
    name = str(action.observed.body.get("name"))
    typed = click.prompt(f"Type the {action.kind} name to confirm deletion of {action.key}", default="",
                         show_default=False)
    return bool(typed.strip() == name)


def _confirm(state: AppState, p: Plan, cfg: Any, ctx: Any) -> None:
    if state.auto_approve:
        return
    if not console.is_interactive():
        raise CliExit(ExitCode.ERROR, "refusing to apply without --auto-approve in a non-interactive session")
    destructive = [a for a in p.visible() if a.type in (ActionType.DELETE, ActionType.REPLACE)
                   or (a.label and "scale in" in a.label)]
    if destructive:
        out("Destructive changes:")
        for a in destructive:
            out(f"  {a.kind} {a.key}")
    rotating = [a for a in p.visible() if a.type is ActionType.UPDATE and a.data.get("rotate")]
    if rotating:  # CAP-028 AC5
        out("Passwords to rotate:")
        for a in rotating:
            out(f"  {a.key}")
    for a in destructive:
        if a.kind in ("bucket", "scope", "collection") and a.type is ActionType.DELETE \
                and not confirm_data_delete(ctx, a):
            out("Apply cancelled; nothing was changed.")
            raise CliExit(ExitCode.OK, "")
    n = sum(1 for a in p.visible() if a.type in (ActionType.CREATE, ActionType.UPDATE, ActionType.REPLACE,
                                                  ActionType.DELETE))
    if not click.confirm(f"Apply {n} change{'s' if n != 1 else ''} to {projects_label(cfg)}?", default=False):
        out("Apply cancelled.")
        raise CliExit(ExitCode.OK, "")


def _connection_strings(ctx: Any, result: ApplyResult) -> list[str]:
    lines = []
    for a in result.actions:
        if a.kind == "cluster" and a.status == "done" and a.id:
            project = a.ancestor("project")
            if project is None or project.id is None:
                continue
            try:
                body, _ = ep.get_cluster(ctx.client, project.id, a.id)
            except Exception:  # noqa: BLE001 - informational only
                continue
            if body.get("connectionString"):
                lines.append(f"connectionString ({a.key}): {body['connectionString']}")
    return lines


@click.command(epilog="\b\nExamples:\n  capellactl apply\n  capellactl apply --auto-approve\n"
                      "  capellactl apply --target cluster/nova-dev-01\n"
                      "  capellactl apply --rotate-passwords --target credential/nova-dev-01/orders_app")
@click.option("--target", "targets", multiple=True, metavar="KIND/NAME", help="Limit to these resources (repeatable).")
@click.option("--prune", is_flag=True, help="Also delete buckets, scopes, collections, allowed CIDRs and database "
              "credentials that exist in Capella but are not in the file (asks for each bucket, scope and "
              "collection name).")
@click.option("--rotate-passwords", is_flag=True, help="Also set a new password on every planned database "
              "credential: the configured ${VAR}/${file:...} value, else a generated one (saved locally).")
@click.option("--power-on", is_flag=True, help="Turn on a turned-off cluster before changing it or what it holds.")
@click.option("--allow-service-removal", is_flag=True, help="Scale-in may remove the last nodes running a service.")
@click.option("--allow-service-group-removal", is_flag=True, help="Scale-in may remove a whole service group.")
@click.option("--skip-capacity-check", is_flag=True, help="Scale in even when cluster stats cannot be read "
              "(at your own risk).")
@pass_state
def apply(state: AppState, targets: tuple[str, ...], prune: bool, rotate_passwords: bool, power_on: bool,
          allow_service_removal: bool, allow_service_group_removal: bool, skip_capacity_check: bool) -> None:
    """Make Capella match the config file. Shows the plan and asks first."""
    run_apply(state, list(targets) or None, prune=prune, rotate_passwords=rotate_passwords, power_on=power_on,
              allow_service_removal=allow_service_removal, allow_service_group_removal=allow_service_group_removal,
              skip_capacity_check=skip_capacity_check)


def run_apply(state: AppState, targets: list[str] | None, descendants: bool = True, prune: bool = False,
              rotate_passwords: bool = False, **options: bool) -> None:
    p, cfg, ctx = make_plan(state, targets, descendants, prune, rotate_passwords, **options)
    apply_plan(state, p, cfg, ctx)


def pin_created_ids(cfg: Any, actions: list[Any]) -> None:
    """Record the id of each project and cluster just created, so a later rename in the Capella UI shows as a
    rename and never as a new resource (CAP-048). Comments and layout of the file are kept."""
    from capellactl.config.editor import ConfigEditor

    created = [a for a in actions if a.kind in ("project", "cluster") and a.type is ActionType.CREATE
               and a.status == "done" and a.id]
    path = getattr(cfg, "path", None)
    if not created or path is None or not path.exists():
        return
    ed = ConfigEditor(path)
    changed = False
    for a in created:
        if a.kind == "project":
            node = ed.find_project(str(a.desired.get("name")))
        else:
            project = a.ancestor("project")
            found = ed.find_cluster(str(a.desired.get("name")), project.key if project else None)
            node = found[1] if found else None
        if node is not None and "id" not in node:
            node.insert(0, "id", a.id)
            changed = True
    if changed:
        path.write_text(ed.text(), encoding="utf-8")


def apply_plan(state: AppState, p: Plan, cfg: Any, ctx: Any, after: list[str] | None = None,
               shown: bool = False, on_failure: Callable[[ApplyResult], str | None] | None = None) -> None:
    """Show, confirm and execute a plan; shared by apply and the resource create/update commands.

    `shown=True`: the caller already displayed the plan and got confirmation.
    `on_failure`: called with the result when an action fails; a returned line replaces the "re-run apply" advice.
    """
    if p.blocked:
        if state.json:
            out(dumps(render_plan_json(p)))
        else:
            out(render_plan_text(p, plan_header(cfg, ctx.client)))
        raise CliExit(ExitCode.BLOCKED, f"Apply refused: {len(p.blocked)} blocked change(s); nothing was changed.",
                      topic=p.blocked[0].topic)
    if not p.has_changes:
        if state.json:
            out(dumps({**render_plan_json(p), "result": {"status": "ok", "actions": []}}))
            return
        deferred = [a for a in p.visible() if a.type is ActionType.DEFERRED]
        if deferred:
            out(render_plan_text(Plan(deferred)).rsplit("\n\n", 1)[0])
        if p.unmanaged:
            out("Unmanaged (not in capella.yaml):")
            for label in p.unmanaged:
                out(f"    {label}")
        out("No changes. Capella matches capella.yaml.")
        return
    if not shown:
        if not state.json:
            out(render_plan_text(p, plan_header(cfg, ctx.client)))
            out("")
        _confirm(state, p, cfg, ctx)
    started = ctx.clock.monotonic()
    result = execute(ctx, p)
    pin_created_ids(cfg, result.actions)
    conn = _connection_strings(ctx, result) if result.ok else []
    if state.json:
        payload = {**render_plan_json(p), "result": result.to_json()}
        if conn:
            payload["result"]["connectionStrings"] = conn
        out(dumps(payload))
    else:
        table = render_summary_table(result.actions)
        if table:
            out("")
            out(table)
        for line in conn:
            out(line)
    if result.interrupted:
        detail = result.failed.error if result.failed and result.failed.error else "Interrupted"
        raise CliExit(ExitCode.INTERRUPTED, f"{detail}; re-run apply to continue.")
    if result.failed:
        failed = result.failed
        code = ExitCode.TIMEOUT if isinstance(result.error, WaitTimeout) else ExitCode.ERROR
        msg = f"Failed: {failed.kind} {failed.key}: {failed.error}"
        hint = getattr(result.error, "hint", None)
        if isinstance(result.error, ServerError) and result.error.method in ("POST", "PUT"):
            # Capella answers some unsupported values with a bare 500 ("something went wrong on our end").
            hint = (f"Capella returned an internal error for this {failed.kind}. This is often caused by a value "
                    f"Capella does not support (for example a region, size or disk not offered for the provider) "
                    f"rather than an outage: check the values in the plan above and try again; if they are correct, "
                    f"retry later or contact Capella support.")
        if hint:
            msg += f"\nHint: {hint}"
        if isinstance(result.error, Forbidden):
            roles = ep.required_roles(result.error.method, result.error.path)
            if roles:
                msg += f"\nrequired role: {roles}"
        done = [a for a in result.actions if a.status == "done"]
        if done:
            msg += "\nCompleted before the failure: " + ", ".join(f"{a.kind} {a.key}" for a in done)
        undone = on_failure(result) if on_failure else None
        msg += f"\n{undone}" if undone else "\nFix the problem and re-run apply; completed changes are not repeated."
        raise CliExit(code, msg)
    for line in after or []:
        err(line)
    if not state.json:
        err(f"Apply complete in {format_duration(ctx.clock.monotonic() - started)}.")


# ------------------------------------------------------------- not yet built
def protected_clusters(state: AppState) -> list[str]:
    """Clusters declared in the file that have deletion protection on in Capella (CAP-013 AC4)."""
    from capellactl.resources.guards import deletion_protected

    cfg = state.load_config()
    client = state.client(cfg.organization_id)
    projects = ep.list_projects(client)
    names = []
    for entry in cfg.projects():
        pinned = entry.data.get("id")
        match = [p for p in projects if (p.get("id") == pinned if pinned else p.get("name") == entry.name)]
        for proj in match:
            declared = {(c.get("id"), c.get("name")) for c in entry.clusters}
            for c in ep.list_clusters(client, str(proj["id"])):
                hit = any((i == c.get("id")) if i else (n == c.get("name")) for i, n in declared)
                if hit and deletion_protected(c):
                    names.append(str(c.get("name")))
    return names


DESTROY_ORDER_NOTE = "credentials → collections → scopes → buckets → CIDRs → schedule → cluster → project"


def destroy_plan(ctx: Any, plan: Plan, discard_snapshots: bool) -> tuple[Plan, list[str]]:
    """Deletes for every resource the file declares that exists, children first (reverse of the apply order).

    A project is kept when Capella holds clusters the file does not declare (CAP-030 AC6); a turned-off cluster's
    contents are left to the cluster delete (Capella deletes them with it)."""
    deletes: list[Any] = []
    kept: list[str] = []
    skip_below: set[int] = set()
    for a in plan.actions:
        if a.kind == "cluster" and a.observed is not None and a.data.get("state") not in ("healthy", None):
            skip_below.add(id(a))
    for a in reversed(plan.actions):
        if a.observed is None or a.kind == "deletion-protection" or a.type is ActionType.DELETE:
            continue
        anc, under_off = a.parent, False
        while anc is not None:
            under_off = under_off or id(anc) in skip_below
            anc = anc.parent
        if under_off:
            continue
        if a.kind == "project":
            declared = {c.get("id") or c.get("name") for c in a.desired.get("_clusters") or [] if isinstance(c, dict)}
            others = [c for c in ep.list_clusters(ctx.client, str(a.observed.id))
                      if c.get("id") not in declared and c.get("name") not in declared]
            if others:
                kept.append(f"project {a.key} kept: contains undeclared cluster "
                            f"{', '.join(str(c.get('name')) for c in others)}")
                continue
        d = a.reconciler.delete_action(ctx, a.observed, a.parent)
        if a.kind == "cluster":
            d.data["discard_snapshots"] = discard_snapshots
        deletes.append(d)
    return Plan(deletes), kept


@click.command(epilog="\b\nExamples:\n  capellactl destroy\n  capellactl --auto-approve destroy\n"
                      "  capellactl destroy --discard-snapshots")
@click.option("--discard-snapshots", is_flag=True, help="Also delete the clusters' snapshot backups (kept by default).")
@pass_state
def destroy(state: AppState, discard_snapshots: bool) -> None:
    """Delete every resource the file declares, in reverse order (CAP-030). capella.yaml is kept (only the ids of
    what was deleted are dropped), so 'apply' builds it all again."""
    from capellactl.resources.guards import protection_message

    protected = protected_clusters(state)
    if protected:  # checked before anything else (CAP-013 AC4, CAP-030 AC5)
        raise CliExit(ExitCode.BLOCKED, "\n".join(protection_message(n) for n in protected) + "\nNothing was deleted.",
                      topic="safety")
    p, cfg, ctx = make_plan(state)
    deletes, kept = destroy_plan(ctx, p, discard_snapshots)
    if not deletes.actions:
        for line in kept:
            out(line)
        out("nothing to destroy: none of the resources in capella.yaml exist in Capella")
        return
    if state.json:
        out(dumps(render_plan_json(deletes)))
    else:
        out(render_plan_text(deletes, plan_header(cfg, ctx.client)))
        out("")
        for line in kept:
            out(line)
    if not state.auto_approve:
        if not console.is_interactive():
            raise CliExit(ExitCode.ERROR, "refusing to destroy without --auto-approve in a non-interactive session")
        out(f"This deletes everything listed above ({DESTROY_ORDER_NOTE}). Snapshot backups are "
            f"{'deleted' if discard_snapshots else 'kept'}.")
        names = cfg.project_names()
        typed = click.prompt(f"Type {'the project name' if len(names) == 1 else 'the project names, comma-separated'} "
                             "to confirm", default="", show_default=False)
        if sorted(t.strip() for t in typed.split(",")) != sorted(names):
            out("Destroy cancelled; nothing was deleted.")
            return
    started = ctx.clock.monotonic()
    result = execute(ctx, deletes)
    if not state.json:
        table = render_summary_table(result.actions)
        if table:
            out("")
            out(table)
    if result.failed or result.interrupted:
        failed = result.failed
        detail = f"{failed.kind} {failed.key}: {failed.error}" if failed else "interrupted"
        raise CliExit(ExitCode.TIMEOUT if isinstance(result.error, WaitTimeout) else ExitCode.ERROR,
                      f"Failed: {detail}\nRe-run destroy to continue; what is already deleted is skipped.")
    for line in kept:
        err(line)
    unpin_deleted(cfg, result.actions)
    err(f"Destroy complete in {format_duration(ctx.clock.monotonic() - started)}. capella.yaml still describes the "
        "environment: run 'capellactl apply' to build it again.")


def unpin_deleted(cfg: Any, actions: list[Any]) -> None:
    """Drop the `id:` of each project and cluster destroy deleted: those ids are gone, and a pinned id that does not
    exist stops apply (CAP-048). Everything else in capella.yaml stays, so apply builds the same environment."""
    from capellactl.config.editor import ConfigEditor

    gone = [a for a in actions if a.kind in ("project", "cluster") and a.type is ActionType.DELETE
            and a.status == "done"]
    path = getattr(cfg, "path", None)
    if not gone or path is None or not path.exists():
        return
    ed = ConfigEditor(path)
    changed = False
    for a in gone:
        if a.kind == "project":
            node = ed.find_project(str(a.desired.get("name")))
        else:
            project = a.ancestor("project")
            found = ed.find_cluster(str(a.desired.get("name")), project.key if project else None)
            node = found[1] if found else None
        if node is not None and "id" in node:
            del node["id"]
            changed = True
    if changed:
        backup = ed.save()
        err(f"{path.name}: removed the ids of the deleted project and clusters (previous version kept as "
            f"{backup.name})")


@click.command(epilog="\b\nExamples:\n  capellactl drift\n  capellactl drift --detailed-exitcode     (CI: exit 2 on drift)\n"
                      "  capellactl -o json drift")
@click.option("--detailed-exitcode", is_flag=True, help="Exit 2 when Capella and capella.yaml differ, 0 when not.")
@pass_state
def drift(state: AppState, detailed_exitcode: bool) -> None:
    """Report what differs between Capella and capella.yaml, including resources made outside capellactl (CAP-031).

    Read-only: only GET requests. Changed and missing items are fixed by 'apply'; unmanaged ones are removed by
    'apply --prune' (never clusters or projects) or brought into the file by 'sync'."""
    p, cfg, ctx = make_plan(state, all_unmanaged=True)
    visible = p.visible()
    changed = [a for a in visible if a.type in (ActionType.UPDATE, ActionType.REPLACE, ActionType.DELETE)
               or (a.type is ActionType.BLOCKED and a.observed is not None)]
    missing = [a for a in visible if a.type is ActionType.CREATE
               or (a.type is ActionType.BLOCKED and a.observed is None)]
    found = bool(changed or missing or p.unmanaged)
    if state.json:
        out(dumps({"changed": [a.to_json() for a in changed], "missing": [a.to_json() for a in missing],
                   "unmanaged": list(p.unmanaged)}))
    else:
        out(plan_header(cfg, ctx.client))
        sections = [("Changed (capella.yaml differs from Capella; 'apply' changes Capella):", changed),
                    ("Missing (in capella.yaml, not in Capella; 'apply' creates them):", missing)]
        for title, items in sections:
            if items:
                out("")
                out(title)
                for a in items:
                    for line in render_plan_text(Plan([a])).split("\n\n")[0].splitlines():
                        out(line)
        if p.unmanaged:
            out("")
            out("Unmanaged (in Capella, not in capella.yaml; 'apply --prune' deletes them, 'sync' adds them to the "
                "file):")
            for label in p.unmanaged:
                out(f"    {label}")
        out("")
        out(f"Drift: {len(changed)} changed, {len(missing)} missing, {len(p.unmanaged)} unmanaged." if found
            else "No drift: Capella matches capella.yaml.")
    if detailed_exitcode and found:
        raise CliExit(ExitCode.CHANGES, "")


def _choose_project(client: Any, name: str | None, project_id: str | None) -> dict[str, Any]:
    projects = ep.list_projects(client)
    if project_id:
        found = [p for p in projects if p.get("id") == project_id]
        if not found:
            raise CliExit(ExitCode.ERROR, f"project {project_id} not found")
        return found[0]
    if name:
        found = [p for p in projects if p.get("name") == name]
        if not found:
            names = ", ".join(sorted(str(p.get("name")) for p in projects)) or "none"
            raise CliExit(ExitCode.ERROR, f"project {name} not found (projects: {names})")
        if len(found) > 1:
            ids = ", ".join(str(p["id"]) for p in found)
            raise CliExit(ExitCode.BLOCKED, f"{len(found)} projects are named {name} (ids: {ids}); pass --project-id",
                          topic="idempotency")
        return found[0]
    if not projects:
        raise CliExit(ExitCode.ERROR, "this organization has no projects yet; create one with "
                                      "'capellactl project create NAME'")
    if len(projects) == 1:
        return projects[0]
    if not console.is_interactive():
        names = ", ".join(sorted(str(p.get("name")) for p in projects))
        raise CliExit(ExitCode.CONFIG_INVALID, f"several projects ({names}); pass --project NAME")
    out("Projects:")
    for i, p in enumerate(projects, 1):
        out(f"  {i}. {p.get('name')}")
    idx = click.prompt("Which project should capella.yaml describe?", type=click.IntRange(1, len(projects)))
    return projects[idx - 1]


def _select_projects(client: Any, names: tuple[str, ...], project_id: str | None) -> list[dict[str, Any]]:
    projects = ep.list_projects(client)
    if not projects:
        raise CliExit(ExitCode.ERROR, "this organization has no projects yet; create one with "
                                      "'capellactl project create NAME'")
    if project_id:
        return [_choose_project(client, None, project_id)]
    if names:
        return [_choose_project(client, n, None) for n in names]
    return projects


def run_import(state: AppState, client: Any = None, projects: tuple[str, ...] = (), project_id: str | None = None,
               clusters: tuple[str, ...] = (), cluster_ids: tuple[str, ...] = (), file: str | None = None,
               full: bool = False, to_stdout: bool = False, force: bool = False) -> None:
    """Discover projects and their clusters and write them to capella.yaml (CAP-036, CAP-040).

    Every project by default (or the named ones). An existing capella.yaml gets the missing projects
    added; projects already in it are left alone (`capellactl sync` refreshes them). Read-only towards Capella.
    """
    from pathlib import Path

    import yaml

    from capellactl.config.editor import ConfigEditor
    from capellactl.config.loader import declared_org_id
    from capellactl.importer import NEW_CLUSTER_TEMPLATE, build_document, combine, render, summary

    client = client or state.client()
    selected = _select_projects(client, projects, project_id)
    path = Path(file) if file else state.config_path()

    editor: ConfigEditor | None = None
    if path.exists() and not to_stdout and not force:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            raw = None
        if isinstance(raw, dict) and ("projects" in raw or "project" in raw):
            file_org = declared_org_id(path, state.env)
            if file_org and client.org_id and file_org != client.org_id:  # never mix two organizations (CAP-047)
                raise CliExit(ExitCode.CONFIG_INVALID,
                              f"{path} is for organization {file_org}, not {client.org_id}; nothing was written. "
                              f"Pass --force to rewrite it for {client.org_id} (the current file is kept as "
                              f"{path.name}.bak), or --file PATH to write a separate file.")
            editor = ConfigEditor(path)
        elif not console.is_interactive():
            raise CliExit(ExitCode.ERROR, f"{path} already exists and is not a capellactl file; pass --force to "
                                          f"overwrite it (the current file is kept as {path.name}.bak)")
        elif not click.confirm(f"{path} exists. Overwrite it (a backup is kept as {path.name}.bak)?", default=False):
            out("Import cancelled; nothing was written.")
            return

    in_file = set(editor.project_names()) if editor else set()
    to_add = [p for p in selected if p.get("name") not in in_file]
    skipped = [str(p.get("name")) for p in selected if p.get("name") in in_file]
    if editor is not None and not to_add:
        out(f"{path.name} already describes {', '.join(skipped)}; nothing to add. "
            "Use 'capellactl sync' to refresh it from Capella.")
        return

    results = []
    matched: set[str] = set()
    for proj in to_add:
        found = ep.list_clusters(client, str(proj["id"]))
        chosen = found
        if clusters or cluster_ids:
            chosen = [c for c in found if c.get("name") in clusters or c.get("id") in cluster_ids]
            matched.update(str(c.get("name")) for c in chosen)
            matched.update(str(c.get("id")) for c in chosen)
        results.append(build_document(client, proj, chosen, full=full, all_clusters=found))
    missing = [n for n in (*clusters, *cluster_ids) if n not in matched]
    if missing:
        names = ", ".join(str(p.get("name")) for p in to_add)
        raise CliExit(ExitCode.ERROR, f"not found in project {names}: {', '.join(missing)}")
    combined = combine(results, client.org_id)
    try:
        org_name = ep.get_organization(client)[0].get("name")
    except Exception:  # noqa: BLE001 - the name is only used in a comment
        org_name = None
    text = render(combined, org_name)
    if "clusters: []" in text:
        text = text.replace("clusters: []\n", "clusters: []\n" + NEW_CLUSTER_TEMPLATE, 1)
    if to_stdout:
        out(text.rstrip("\n"))
        return

    if editor is not None:
        new_doc = editor._yaml.load(text)
        for node in new_doc["projects"]:
            editor.add_project(node)
        backup = editor.save()
        err(f"previous file saved as {backup}")
    else:
        if path.exists():
            backup = path.with_name(path.name + ".bak")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            err(f"previous file saved as {backup}")
        path.write_text(text, encoding="utf-8")
    for w in combined.warnings:
        err(f"warning: {w}")
    verb = "Added" if editor is not None else "Imported"
    out(f"{summary(combined).replace('Imported', verb, 1)} into {path}")
    if skipped:
        out(f"Already in {path.name} (left as is; 'capellactl sync' refreshes them): {', '.join(skipped)}")
    if combined.counts.get("cluster"):
        out("Next: capellactl plan    (reports no changes for what was imported)")
    else:
        out("Next: capellactl cluster create NAME    (deploys the first cluster of a project)")


@click.command("import", epilog="\b\nExamples:\n  capellactl import\n  capellactl import --project nova-dev\n"
                                "  capellactl import --project nova-dev --cluster nova-dev-01\n"
                                "  capellactl import --project nova-dev --stdout > prod.yaml")
@click.option("--project", "projects", multiple=True, metavar="NAME",
              help="Only these projects (repeatable; default: every project).")
@click.option("--project-id", metavar="ID", help="Project ID, when several projects share a name.")
@click.option("--cluster", "clusters", multiple=True, metavar="NAME", help="Only these clusters (repeatable).")
@click.option("--cluster-id", "cluster_ids", multiple=True, metavar="ID", help="Only these cluster IDs (repeatable).")
@click.option("--file", "file", metavar="PATH", help="Output file (default: capella.yaml, or --config).")
@click.option("--full", is_flag=True, help="Write every field, including values equal to the defaults.")
@click.option("--stdout", "to_stdout", is_flag=True, help="Print the YAML instead of writing a file.")
@click.option("--force", is_flag=True, help="Rewrite the whole file instead of adding missing projects (.bak kept).")
@pass_state
def import_cmd(state: AppState, projects: tuple[str, ...], project_id: str | None, clusters: tuple[str, ...],
               cluster_ids: tuple[str, ...], file: str | None, full: bool, to_stdout: bool, force: bool) -> None:
    """Write your Capella projects and clusters to capella.yaml (read-only; adds missing projects)."""
    run_import(state, None, projects, project_id, clusters, cluster_ids, file, full, to_stdout, force)
