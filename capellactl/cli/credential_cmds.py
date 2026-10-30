"""credential list | get | create | update | delete (CAP-046, CAP-028, CAP-029).

create and update record the credential in capella.yaml and apply it, like the bucket commands; one access
grant can be given with flags (several grants: write them in capella.yaml and run apply). update
--rotate-password sets a new password (CAP-028). delete removes it from Capella and from the file and never
deletes the local file of a generated password (CAP-029).
"""

from __future__ import annotations

from typing import Any

import click
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from capellactl.api import endpoints as ep
from capellactl.cli import console
from capellactl.cli.cluster_ops import change_and_apply, locate, open_editor
from capellactl.cli.console import note, out
from capellactl.cli.env import pass_state
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.groups import SuggestingGroup
from capellactl.cli.resource_cmds import (
    _list_table,
    _table,
    complete_cluster_names,
    file_cluster,
    live_cluster,
)
from capellactl.cli.state import AppState
from capellactl.config.editor import put, to_commented
from capellactl.output.password_gen import FORBIDDEN
from capellactl.output.render import dumps
from capellactl.output.secrets_out import secret_path
from capellactl.resources.credential import access_summary, is_advanced, kept_secret_note, secret_dir_for

PRIVILEGES = {"read": ["data_reader"], "write": ["data_writer"], "read+write": ["data_reader", "data_writer"]}
PROJECT_OPT = click.option("--project", metavar="NAME", help="Project of the cluster (only needed when the name repeats).")


def _access_options(f: Any) -> Any:
    for opt in reversed([
        click.option("--privileges", type=click.Choice(list(PRIVILEGES)), help="read, write or read+write."),
        click.option("--bucket", metavar="NAME", help="Bucket the access applies to: BUCKET.*.* (least privilege)."),
        click.option("--scope", metavar="NAME", help="Scope within --bucket: BUCKET.SCOPE.* (default: the whole bucket)."),
        click.option("--collection", "collections", multiple=True, metavar="NAME",
                     help="Collection within --scope: BUCKET.SCOPE.COLLECTION (repeatable; default: the whole scope)."),
        click.option("--all-buckets", is_flag=True, help="Grant the access on every bucket of the cluster."),
        click.option("--password-env", metavar="VAR", help="Use your own password from env var VAR; records ${VAR} "
                     "(default: Capella generates one). Must meet the password rules below."),
        click.option("--password-file", metavar="PATH", help="Use your own password read from file PATH; records "
                     "${file:PATH}. Must meet the password rules below."),
    ]):
        f = opt(f)
    return f


# Capella's rules (Management API spec, CreateDatabaseCredentialRequest.password); checked offline by meets_rules().
PASSWORD_RULES = (
    "\b\nPassword rules (Capella; checked before anything is sent):\n"
    "  - at least 8 characters\n"
    "  - at least one upper-case letter (A-Z), one lower-case letter (a-z), one digit (0-9)\n"
    "    and one special character\n"
    f"  - none of these characters: {' '.join(sorted(FORBIDDEN, key='<>;.*&|£'.index))}\n"
)

CREATE_EXAMPLES = (
    "\b\nExamples (access):\n"
    "  # whole bucket (travel-sample.*.*)\n"
    "  capellactl credential create nova-dev-01 app_ro --privileges read --bucket travel-sample\n"
    "  # one scope (travel-sample.inventory.*)\n"
    "  capellactl credential create nova-dev-01 app_rw --privileges read+write --bucket travel-sample "
    "--scope inventory\n"
    "  # chosen collections (travel-sample.inventory.airline and .route)\n"
    "  capellactl credential create nova-dev-01 app_rw --privileges read+write --bucket travel-sample "
    "--scope inventory --collection airline --collection route\n"
    "  # every bucket of the cluster\n"
    "  capellactl credential create nova-dev-01 dba --privileges read+write --all-buckets\n"
    "\n\b\nExamples (password):\n"
    "  # no password flag: Capella generates one, saved to ./.capellactl/credentials/CLUSTER.NAME.json\n"
    "  # (the credentialsOutput setting, mode 0600); it is never printed\n"
    "  capellactl credential create nova-dev-01 app_ro --bucket travel-sample\n"
    "  # your own password from an environment variable (capella.yaml stores ${APP_PW}, not the value)\n"
    "  export APP_PW='S3cure-Passw0rd!'\n"
    "  capellactl credential create nova-dev-01 app_ro --bucket travel-sample --password-env APP_PW\n"
    "  # your own password from a file (capella.yaml stores ${file:./secrets/app.pw})\n"
    "  capellactl credential create nova-dev-01 app_ro --bucket travel-sample --password-file ./secrets/app.pw\n"
    "\n\b\nOnly record it in capella.yaml (apply later):\n"
    "  capellactl credential create nova-dev-01 app_ro --bucket travel-sample --no-apply\n"
    "\n" + PASSWORD_RULES
)


@click.group(cls=SuggestingGroup, epilog="\b\nExamples:\n  capellactl credential list nova-dev-01\n"
                                         "  capellactl credential get nova-dev-01 app_ro\n"
                                         "  capellactl credential update nova-dev-01 app_ro --rotate-password\n"
                                         "  capellactl credential delete nova-dev-01 app_ro\n\n" + CREATE_EXAMPLES)
def credential() -> None:
    """Database credentials: list, get, create, update, delete."""


# --------------------------------------------------------------------- read
def _declared(state: AppState, cluster: str, project: str | None) -> set[str]:
    return {str(u.get("name")) for u in (file_cluster(state, cluster, project) or {}).get("databaseCredentials") or []
            if isinstance(u, dict)}


def _find(client: Any, pid: str, cid: str, name: str) -> dict[str, Any] | None:
    return next((u for u in ep.list_credentials(client, pid, cid) if u.get("name") == name), None)


def _type(u: dict[str, Any]) -> str:
    return "advanced" if is_advanced(u) else "basic"


def _secret_dir(state: AppState) -> Any:
    try:
        return secret_dir_for(state.load_config())
    except CliExit:
        return secret_dir_for(None)


@credential.command("list")
@click.argument("cluster", shell_complete=complete_cluster_names)
@PROJECT_OPT
@pass_state
def credential_list(state: AppState, cluster: str, project: str | None) -> None:
    """List the database credentials of a cluster (passwords are never shown)."""
    client, pid, cl = live_cluster(state, cluster, project)
    items = ep.list_credentials(client, pid, str(cl["id"]))
    if state.json:
        out(dumps(items))
        return
    declared = _declared(state, cluster, project)
    rows: list[tuple[str, ...]] = [("NAME", "TYPE", "ACCESS", "IN FILE")]
    for u in items:
        access = "userRoles" if is_advanced(u) else access_summary(u.get("access"))
        rows.append((str(u.get("name")), _type(u), access, "yes" if u.get("name") in declared else "-"))
    out(_list_table(rows))


@credential.command("get")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("name")
@PROJECT_OPT
@pass_state
def credential_get(state: AppState, cluster: str, name: str, project: str | None) -> None:
    """Show one credential: type and access (Capella never returns the password)."""
    client, pid, cl = live_cluster(state, cluster, project)
    found = _find(client, pid, str(cl["id"]), name)
    if found is None:
        raise CliExit(ExitCode.ERROR, f"credential {cluster}/{name} not found",
                                      action=f"Check the name with 'capellactl credential list {cluster}'.")
    body, _ = ep.get_credential(client, pid, str(cl["id"]), str(found["id"]))
    if state.json:
        out(dumps(body))
        return
    rows = [("FIELD", "VALUE"), ("id", str(body.get("id"))), ("name", str(body.get("name"))), ("type", _type(body))]
    if is_advanced(body):
        rows.append(("userRoles", ", ".join(str(r) for r in body.get("userRoles") or []) or "-"))
    else:
        rows += [("access", line) for line in access_summary(body.get("access")).split("; ")]
    local = secret_path(_secret_dir(state), cluster, name)
    if local.exists():
        rows.append(("generated password", f"saved in {local}"))
    out(_table(rows))


# ------------------------------------------------------------ create/update
def _grant(privileges: str | None, bucket: str | None, scope: str | None, collections: tuple[str, ...],
           all_buckets: bool) -> dict[str, Any] | None:
    """One access grant from the flags; None when no access flag was given."""
    if not (privileges or bucket or scope or collections or all_buckets):
        return None
    if scope and not bucket:
        raise CliExit(ExitCode.CONFIG_INVALID, "--scope was given without --bucket",
                                               action="Add --bucket with the bucket the scope is in.")
    if collections and not scope:
        raise CliExit(ExitCode.CONFIG_INVALID, "--collection was given without --scope",
                                               action="Add --scope with the scope the collection is in.")
    if bucket and all_buckets:
        raise CliExit(ExitCode.CONFIG_INVALID, "both --bucket and --all-buckets were given",
                                               action="Keep one: --bucket NAME for one bucket, or --all-buckets for "
                                                      "every bucket.")
    if not bucket and not all_buckets:
        raise CliExit(ExitCode.CONFIG_INVALID, "no bucket was given for the access", topic="credentials",
                                               action="Add --bucket NAME (least privilege), or --all-buckets for "
                                                      "every bucket.")
    grant: dict[str, Any] = {"privileges": PRIVILEGES[privileges or "read"]}
    if bucket:
        rb: dict[str, Any] = {"name": bucket}
        if scope:
            rb["scopes"] = [{"name": scope, **({"collections": list(collections)} if collections else {})}]
        grant["resources"] = {"buckets": [rb]}
    return grant


def _password_ref(env_var: str | None, file: str | None) -> str | None:
    if env_var and file:
        raise CliExit(ExitCode.CONFIG_INVALID, "both --password-env and --password-file were given",
                                               action="Keep one of them.")
    return f"${{{env_var}}}" if env_var else f"${{file:{file}}}" if file else None


def _node(cl: CommentedMap, name: str) -> CommentedMap | None:
    return next((u for u in cl.get("databaseCredentials") or [] if isinstance(u, CommentedMap) and u.get("name") == name),
                None)


@credential.command("create", epilog=CREATE_EXAMPLES)
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("name")
@_access_options
@PROJECT_OPT
@click.option("--no-apply", is_flag=True, help="Only add the credential to capella.yaml; create it later with apply.")
@pass_state
def credential_create(state: AppState, cluster: str, name: str, privileges: str | None, bucket: str | None,
                      scope: str | None, collections: tuple[str, ...], all_buckets: bool, password_env: str | None,
                      password_file: str | None, project: str | None, no_apply: bool) -> None:
    """Create a basic credential: records it in capella.yaml and creates it in Capella (an existing one is adopted).

    Access: --bucket B is B.*.*, add --scope S for B.S.*, add --collection C (repeatable) for B.S.C.

    Password: there is no default password. Without --password-env/--password-file Capella generates one; it is
    saved once to the credentialsOutput directory (default ./.capellactl/credentials/CLUSTER.NAME.json, mode 0600)
    and never printed. The password is never taken on the command line, so it does not end up in shell history.
    """
    ed = open_editor(state)
    _, cl = locate(ed, cluster, project)
    if _node(cl, name) is not None:
        raise CliExit(ExitCode.BLOCKED, f"credential {name} is already in capella.yaml for {cluster}", topic="idempotency",
                                        action=f"Change it with 'capellactl credential update {cluster} {name}'.")
    grant = _grant(privileges, bucket, scope, collections, all_buckets)
    if grant is None:
        raise CliExit(ExitCode.CONFIG_INVALID, "no bucket was given for the access",
                      topic="credentials",
                                               action="Add --bucket NAME (least privilege), or --all-buckets for "
                                                      "every bucket.")
    entry: dict[str, Any] = {"name": name}
    ref = _password_ref(password_env, password_file)
    if ref:
        entry["password"] = ref
    entry["access"] = [grant]
    if "databaseCredentials" not in cl or not isinstance(cl.get("databaseCredentials"), CommentedSeq):
        put(cl, "databaseCredentials", CommentedSeq())
    cl["databaseCredentials"].append(to_commented(entry))
    change_and_apply(state, ed, f"credential/{cluster}/{name}",
                     f"Add credential {name} to capella.yaml and create it in {cluster}?", no_apply,
                     noop_message=f"credential {cluster}/{name} already exists in Capella with this access; recorded "
                                  "it in capella.yaml (its password is unchanged)")


@credential.command("update", epilog="\b\nExamples:\n  capellactl credential update nova-dev-01 orders_app "
                                      "--privileges read --bucket orders\n"
                                      "  capellactl credential update nova-dev-01 orders_app --rotate-password\n"
                                      "  capellactl credential update nova-dev-01 orders_app --password-env NEW_PW "
                                      "--rotate-password\n\n" + PASSWORD_RULES)
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("name")
@_access_options
@click.option("--rotate-password", is_flag=True, help="Set a new password: the configured ${VAR}/${file:...} value, "
              "else a generated one (saved locally, previous file kept as .bak).")
@PROJECT_OPT
@click.option("--no-apply", is_flag=True, help="Only update capella.yaml; apply later.")
@pass_state
def credential_update(state: AppState, cluster: str, name: str, privileges: str | None, bucket: str | None,
                      scope: str | None, collections: tuple[str, ...], all_buckets: bool, password_env: str | None,
                      password_file: str | None, rotate_password: bool, project: str | None, no_apply: bool) -> None:
    """Change a credential's access (one grant) or password source, or rotate its password; records it and applies.

    Access flags replace the credential's access with one grant. A changed password reference is used at the next
    rotation; passwords change only with --rotate-password.
    """
    ed = open_editor(state)
    _, cl = locate(ed, cluster, project)
    node = _node(cl, name)
    if node is None:
        raise CliExit(ExitCode.CONFIG_INVALID, f"credential {name} is not in capella.yaml for {cluster}",
                                               action=f"Add it with 'capellactl credential create {cluster} {name}' "
                                                      f"(a credential that exists in Capella is adopted, not created "
                                                      f"again), then run the command again.")
    grant = _grant(privileges, bucket, scope, collections, all_buckets)
    ref = _password_ref(password_env, password_file)
    if grant is None and ref is None and not rotate_password:
        raise CliExit(ExitCode.CONFIG_INVALID, "nothing to change: no option was given",
                                               action="Add --privileges with --bucket or --all-buckets, "
                                                      "--password-env or --password-file, or --rotate-password.")
    if grant is not None:
        if len(node.get("access") or []) > 1:
            raise CliExit(ExitCode.CONFIG_INVALID, f"credential {name} has several access grants, and this command "
                                                   f"changes one",
                                                   action=f"Delete it with 'capellactl credential delete {cluster} "
                                                          f"{name}' and create it again with the access it needs "
                                                          f"(keep its password with --password-env).")
        node["access"] = to_commented([grant])
    if ref is not None:
        node["password"] = ref
    question = (f"Rotate the password of {name}?" if rotate_password and grant is None and ref is None
                else f"Record these changes in capella.yaml and apply them to credential {name}?")
    change_and_apply(state, ed, f"credential/{cluster}/{name}", question, no_apply, rotate_passwords=rotate_password)


# ------------------------------------------------------------------- delete
@credential.command("delete", epilog="\b\nExamples:\n  capellactl credential delete nova-dev-01 reporting_ro\n"
                                      "  capellactl --auto-approve credential delete nova-dev-01 reporting_ro")
@click.argument("cluster", shell_complete=complete_cluster_names)
@click.argument("name")
@PROJECT_OPT
@pass_state
def credential_delete(state: AppState, cluster: str, name: str, project: str | None) -> None:
    """Delete a credential from Capella (applications using it lose access) and remove it from capella.yaml."""
    client, pid, cl = live_cluster(state, cluster, project)
    cid = str(cl["id"])
    found = _find(client, pid, cid, name)
    directory = _secret_dir(state)
    if found is None:
        out(f"credential {cluster}/{name} not found, nothing to do")
        _remove_from_file(state, cluster, name, project)
        return
    summary = "advanced (userRoles)" if is_advanced(found) else access_summary(found.get("access"))
    out(f"  - credential {cluster}/{name}  {summary}")
    if not console.confirm(state, f"Applications using {name} will lose access to {cluster}. Delete it?",
                           "delete a database credential"):
        out("Cancelled; nothing was deleted.")
        return
    ep.delete_credential(client, pid, cid, str(found["id"]))  # the id always comes from the list response
    out(f"deleted credential {cluster}/{name}")
    note = kept_secret_note(directory, cluster, name)
    if note:
        out(note)
    _remove_from_file(state, cluster, name, project)


def _remove_from_file(state: AppState, cluster: str, name: str, project: str | None) -> None:
    """Keep capella.yaml in step, so the next apply does not create the credential again."""
    from capellactl.config.editor import ConfigEditor

    path = state.config_path()
    if not path.exists() or name not in _declared(state, cluster, project):
        return
    ed = ConfigEditor(path)
    try:
        found = ed.find_cluster(cluster, project)
    except LookupError:
        return
    if found is None:
        return
    seq = found[1].get("databaseCredentials") or []
    for i, u in enumerate(seq):
        if isinstance(u, CommentedMap) and u.get("name") == name:
            del seq[i]
            break
    if not seq:
        del found[1]["databaseCredentials"]
    backup = ed.save()
    note(f"removed credential {name} from {path.name} (previous version kept as {backup.name})")
