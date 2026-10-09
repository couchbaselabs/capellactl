"""capellactl configure: profiles and keychain-stored API keys (CAP-037)."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import click

from capellactl import DEFAULT_BASE_URL
from capellactl.api import endpoints as ep
from capellactl.api.client import CapellaClient
from capellactl.api.errors import CapellaApiError, Unauthorized
from capellactl.cli import console
from capellactl.cli.console import out
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.groups import SuggestingGroup
from capellactl.cli.state import AppState
from capellactl.config import settings as st
from capellactl.config.loader import declared_org_id
from capellactl.engine.clock import get_clock
from capellactl.output.render import dumps

pass_state = click.make_pass_decorator(AppState)

_PASTE_MARKERS = re.compile(r"\x1b\[20[01]~")  # bracketed-paste markers some terminals add
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean_api_key(raw: str) -> tuple[str, list[str]]:
    """Undo common copy/paste damage. Returns the key and what was fixed (never the key itself)."""
    fixed: list[str] = []
    key = raw
    if _PASTE_MARKERS.search(key):
        key = _PASTE_MARKERS.sub("", key)
        fixed.append("removed terminal paste markers")
    key = key.strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in "'\"":
        key = key[1:-1].strip()
        fixed.append("removed surrounding quotes")
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
        fixed.append("removed a leading 'Bearer '")
    inner = sum(1 for c in key if c.isspace() or _CONTROL.match(c))
    if inner:
        key = "".join(c for c in key if not (c.isspace() or _CONTROL.match(c)))
        fixed.append(f"removed {inner} line break/space/control character(s)")
    return key, fixed


def rejection_help(key: str, base_url: str, message: str, hint: str | None) -> str:
    tail = key[-4:] if len(key) >= 8 else "?"
    lines = [
        f"API Key Token rejected by Capella (HTTP 401: {message}); nothing was saved.",
    ]
    if hint:
        lines.append(f"Capella says: {hint}")
    lines += [
        f"The key received has {len(key)} characters and ends in …{tail}. Check that:",
        "  1. this machine's public IP is in the API key's allowed IP list (Capella UI → Organization settings →",
        "     API Keys → your key). Find your IP with: curl -s https://checkip.amazonaws.com",
        "  2. you copied the API Key Token (shown once when the key is created), not the API Key ID or name;",
        "  3. the key has not expired or been deleted;",
        f"  4. the API URL is right (now: {base_url}; change with --api-base-url).",
    ]
    if len(key) >= 1000:
        lines.append("  Note: the key is 1000+ characters; the terminal may have cut it. Use --api-key-stdin.")
    lines += [
        "Test the key without capellactl (prints 200 when it works):",
        f"  curl -s -o /dev/null -w '%{{http_code}}\\n' -H \"Authorization: Bearer $CAPELLA_API_KEY\" {base_url}/v4/organizations",
        "Avoid pasting into the hidden prompt: pbpaste | capellactl configure --api-key-stdin",
    ]
    return "\n".join(lines)


def _profile_name(state: AppState, local: str | None) -> str:
    return local or state.profile_flag or state.env.get("CAPELLACTL_PROFILE") or st.DEFAULT_PROFILE


@click.group(cls=SuggestingGroup, invoke_without_command=True,
             epilog="\b\nExamples:\n  capellactl configure\n  capellactl configure --profile prod\n"
                    "  capellactl configure list\n  capellactl configure show\n"
                    "  capellactl configure remove --profile old")
@click.option("--profile", "local_profile", metavar="NAME", help="Profile to create or update (default: 'default').")
@click.option("--org-id", metavar="ID", help="Organization to use without asking.")
@click.option("--api-base-url", metavar="URL", default=None, help=f"Default {DEFAULT_BASE_URL}.")
@click.option("--config-file", metavar="PATH", default=None, help="Default config file for this profile.")
@click.option("--import/--no-import", "do_import", default=None,
              help="After saving, discover your project and clusters and write capella.yaml (asked by default).")
@click.option("--api-key-stdin", is_flag=True,
              help="Read the API Key Token from standard input instead of a prompt (e.g. pbpaste | capellactl configure "
                   "--api-key-stdin).")
@click.pass_context
def configure(ctx: click.Context, local_profile: str | None, org_id: str | None, api_base_url: str | None,
              config_file: str | None, do_import: bool | None, api_key_stdin: bool) -> None:
    """Save a Capella API Key Token (OS keychain) and organization as a profile."""
    if ctx.invoked_subcommand is not None:
        ctx.meta["local_profile"] = local_profile
        return
    state: AppState = ctx.ensure_object(AppState)
    name = _profile_name(state, local_profile)
    base_url = api_base_url or DEFAULT_BASE_URL

    if api_key_stdin:
        raw = sys.stdin.read()
    else:
        out("Paste the API Key Token from Capella (Organization settings → API Keys). It is shown once when the key "
            "is created; the API Key ID will not work.")
        raw = console.ask("Capella API Key Token (input hidden)", flag="--api-key-stdin", hide_input=True)
    key, fixed = clean_api_key(raw)
    if not key:
        raise CliExit(ExitCode.CONFIG_INVALID, "no API Key Token entered")
    for note in fixed:
        out(f"note: {note} from the pasted key")
    client = CapellaClient(key, None, base_url, clock=get_clock())
    try:
        orgs = ep.list_organizations(client)
    except Unauthorized as exc:
        raise CliExit(ExitCode.ERROR, rejection_help(key, base_url, exc.message, exc.hint),
                      topic="environment") from None
    if not orgs:
        raise CliExit(ExitCode.ERROR, "this API key cannot see any organization; nothing was saved")

    chosen = None
    if org_id:
        chosen = next((o for o in orgs if o.get("id") == org_id), None)
        if chosen is None:
            raise CliExit(ExitCode.ERROR, f"organization {org_id} is not visible to this API key; nothing was saved")
    elif len(orgs) == 1:
        chosen = orgs[0]
    elif api_key_stdin:  # stdin held the key, so there is no terminal left to ask which organization
        names = ", ".join(f"{o.get('name')} ({o.get('id')})" for o in orgs)
        raise CliExit(ExitCode.CONFIG_INVALID, f"this key sees several organizations ({names}); pass --org-id ID")
    else:
        out("Organizations:")
        for i, o in enumerate(orgs, 1):
            out(f"  {i}. {o.get('name')} ({o.get('id')})")
        idx = console.ask("Choose an organization", flag="--org-id", type=click.IntRange(1, len(orgs)))
        chosen = orgs[idx - 1]

    profiles = st.load_profiles(state.env)
    entry = dict(profiles.get(name, {}))
    entry["organizationId"] = chosen["id"]
    entry["organizationName"] = chosen.get("name", "")
    if api_base_url:
        entry["apiBaseUrl"] = api_base_url
    if config_file:
        entry["configFile"] = config_file

    if st.keychain_available():
        st.keychain_set(name, key)
        stored = "API Key Token stored in the OS keychain"
    else:
        stored = ("no OS keychain available; set CAPELLA_API_KEY in your environment instead "
                  "(the key was not saved)")
    profiles[name] = entry
    path = st.save_profiles(profiles, state.env)
    out(f"profile '{name}' saved (org {chosen.get('name', chosen['id'])}) in {path}")
    out(stored)
    _offer_import(state, CapellaClient(key, str(chosen["id"]), base_url, clock=get_clock()), chosen, do_import,
                  interactive=console.is_interactive() and not api_key_stdin)


def _offer_import(state: AppState, client: CapellaClient, org: dict[str, Any], do_import: bool | None,
                  interactive: bool) -> None:
    """Hand off to `capellactl import` so the user never has to write capella.yaml by hand (CAP-036)."""
    from capellactl.cli.env import run_import

    target = state.config_path()
    if target.exists() and do_import is not True:
        _check_existing(state, client, org, target, prompt=interactive and do_import is None,
                        hint=do_import is None)
        return
    if do_import is False:
        return
    if not ep.list_projects(client):  # a new organization: nothing to discover yet, so point to the next step
        out("This organization has no projects yet. Next: capellactl project create NAME    (creates it in Capella "
            "and writes capella.yaml)")
        return
    if do_import is None:
        if not interactive:
            out("Next: capellactl import    (writes capella.yaml from your Capella project)")
            return
        if not console.ask_yes_no("Discover your projects and clusters and write capella.yaml now?", True):
            out("Later: capellactl import")
            return
    run_import(state, client, force=bool(do_import) and target.exists())


def _check_existing(state: AppState, client: CapellaClient, org: dict[str, Any], target: Path, prompt: bool,
                    hint: bool) -> None:
    """Warn when an existing capella.yaml belongs to another organization or names missing projects (CAP-047).

    Never rewrites the file without an explicit yes; read-only towards Capella."""
    from capellactl.cli.env import run_import
    from capellactl.cli.resource_cmds import file_projects

    org_id = str(org["id"])
    org_name = str(org.get("name") or org_id)
    file_org = declared_org_id(target, state.env)
    if file_org and file_org != org_id:
        out(f"warning: {target} is for organization {file_org}, but this key is for {org_name} ({org_id}).")
        out(f"Commands that read {target} will use organization {file_org} and fail with this key. Either:")
        out(f"  - rewrite it for {org_name} (the current file is kept as {target.name}.bak): capellactl import --force")
        out(f"  - keep it, and save a key for {file_org} in its own profile: capellactl configure --profile NAME")
        if prompt and console.ask_yes_no(f"Back up {target.name} and re-import it for {org_name}?", False):
            run_import(state, client, force=True)
        return
    if hint:
        out(f"{target} already exists; to refresh it from Capella: capellactl import --force")
    declared = [str(p.get("name")) for p in file_projects(state) if p.get("name")]
    if not declared:
        return
    try:
        existing = {str(p.get("name")) for p in ep.list_projects(client)}
    except CapellaApiError:  # the check is advice; the profile is already saved
        return
    names = ", ".join(sorted(existing)) or "none"
    for name in declared:
        if name not in existing:
            out(f"warning: {target} declares project {name}, which is not in organization {org_name} "
                f"(projects: {names})")


@configure.command("list")
@pass_state
def configure_list(state: AppState) -> None:
    """List saved profiles."""
    profiles = st.load_profiles(state.env)
    if state.json:
        out(dumps(profiles))
        return
    if not profiles:
        out("no profiles; run 'capellactl configure'")
        return
    rows = [("PROFILE", "ORGANIZATION", "API BASE URL", "CONFIG FILE", "KEY")]
    for name, p in sorted(profiles.items()):
        has_key = "keychain" if st.keychain_get(name) else "-"
        rows.append((name, f"{p.get('organizationName', '')} ({p.get('organizationId', '')})",
                     str(p.get("apiBaseUrl", DEFAULT_BASE_URL)), str(p.get("configFile", "")), has_key))
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    for r in rows:
        out("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip())


@configure.command("show")
@click.pass_context
def configure_show(ctx: click.Context) -> None:
    """Show the effective settings and where each one comes from."""
    state: AppState = ctx.ensure_object(AppState)
    local = (ctx.parent.meta.get("local_profile") if ctx.parent else None)
    if local:
        state.profile_flag = local
    s = state.settings()
    if state.json:
        out(dumps({k: {"value": v, "source": src} for k, v, src in s.rows()}))
        return
    for k, v, src in s.rows():
        out(f"{k:<14} {v:<48} ({src})")


@configure.command("remove")
@click.pass_context
def configure_remove(ctx: click.Context) -> None:
    """Delete a profile and its keychain entry."""
    state: AppState = ctx.ensure_object(AppState)
    local = ctx.parent.meta.get("local_profile") if ctx.parent else None
    name = _profile_name(state, local)
    profiles = st.load_profiles(state.env)
    had_key = st.keychain_delete(name)
    if name not in profiles and not had_key:
        out(f"profile '{name}': nothing to remove")
        return
    profiles.pop(name, None)
    st.save_profiles(profiles, state.env)
    out(f"profile '{name}' removed" + (" (keychain entry deleted)" if had_key else ""))
