"""capellactl root command (CAP-001)."""

from __future__ import annotations

import logging
import sys
import traceback
from typing import Any

import click

from capellactl import API_VERSION, COPYRIGHT, LICENSE, __version__
from capellactl.api.endpoints import required_roles
from capellactl.api.errors import (
    AmbiguousWriteError,
    CapellaApiError,
    Forbidden,
    TransportError,
    Unauthorized,
)
from capellactl.cli.console import err, set_quiet, setup_logging
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.groups import SuggestingGroup
from capellactl.cli.state import AppState, parse_duration
from capellactl.output.redact import redact

log = logging.getLogger("capellactl")

ROOT_EPILOG = """\b
Examples:
  capellactl configure                 save your API Key Token and organization
  capellactl init                      create capella.yaml with a wizard
  capellactl validate                  check capella.yaml offline
  capellactl plan                      show what would change
  capellactl apply                     make Capella match capella.yaml
  capellactl cluster create NAME       deploy a new cluster (asks for what it needs)
  capellactl sync                      refresh capella.yaml from Capella
  capellactl help topics               concepts: scaling, hibernation, safety …
"""


def api_error_exit(exc: CapellaApiError) -> CliExit:
    if isinstance(exc, Unauthorized):
        msg = ("API Key Token rejected: check that CAPELLA_API_KEY (or your profile, see 'capellactl configure show') "
               "holds the API Key Token, not the API Key ID, and that this machine's public IP is in the key's "
               "allowed IPs")
        if exc.hint:
            msg += f"\nCapella says: {exc.hint}"
        return CliExit(ExitCode.ERROR, msg, topic="environment")
    lines = [f"Error: {exc.message}"]
    if exc.hint:
        lines.append(f"Hint: {exc.hint}")
    if isinstance(exc, Forbidden):
        roles = required_roles(exc.method, exc.path)
        if roles:
            lines.append(f"required role: {roles}")
    return CliExit(ExitCode.ERROR, "\n".join(lines), topic="environment" if isinstance(exc, Forbidden) else None)


class RootGroup(SuggestingGroup):
    """Turns every failure into a clean, redacted message and the right exit code."""

    def invoke(self, ctx: click.Context) -> Any:
        debug = False
        try:
            return super().invoke(ctx)
        except CliExit as exc:
            _report(exc)
            ctx.exit(int(exc.code))
        except CapellaApiError as exc:
            e = api_error_exit(exc)
            _report(e)
            ctx.exit(int(e.code))
        except (AmbiguousWriteError, TransportError) as exc:
            err(f"Error: {exc}")
            ctx.exit(int(ExitCode.ERROR))
        except KeyboardInterrupt:
            err("Interrupted.")
            ctx.exit(int(ExitCode.INTERRUPTED))
        except (click.exceptions.Exit, click.exceptions.Abort, click.ClickException):
            raise
        except Exception as exc:  # noqa: BLE001 - last-resort handler, always redacted
            state = ctx.find_object(AppState)
            debug = bool(state and state.log_level == "debug")
            err(f"Error: {redact(exc)}")
            if debug:
                err(redact("".join(traceback.format_exception(exc))))
            ctx.exit(int(ExitCode.ERROR))
        return None


def _report(exc: CliExit) -> None:
    if exc.message:
        err(exc.message)
    if exc.topic and exc.code not in (ExitCode.OK,):
        err(f"See: capellactl help {exc.topic}")


@click.group(cls=RootGroup, epilog=ROOT_EPILOG, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "--version", message=f"capellactl %(version)s (Management API {API_VERSION})\n"
                                                       f"Licensed under {LICENSE} · {COPYRIGHT}")
@click.option("-c", "--config", "config", metavar="PATH", help="Environment file (default: discovered, see 'help config').")
@click.option("--profile", metavar="NAME", help="Saved profile (see 'capellactl configure').")
@click.option("-o", "--output", type=click.Choice(["text", "json"]), default="text", show_default=True, help="Output format.")
@click.option("--log-level", type=click.Choice(["error", "warn", "info", "debug"]), default="info", show_default=True)
@click.option("--auto-approve", "--yes", "-y", "auto_approve", is_flag=True,
              help="Approve every change without asking (the only approval; see 'help ci').")
@click.option("-q", "--quiet", is_flag=True, envvar="CAPELLACTL_QUIET",
              help="No progress, hints or notes; errors and results are still printed. Env: CAPELLACTL_QUIET.")
@click.option("--no-wait", is_flag=True, help="Return as soon as async operations are accepted.")
@click.option("--timeout", default="60m", show_default=True, metavar="DURATION", help="Max wait for async operations.")
@click.pass_context
def cli(ctx: click.Context, config: str | None, profile: str | None, output: str, log_level: str,
        auto_approve: bool, quiet: bool, no_wait: bool, timeout: str) -> None:
    """Declarative, idempotent management of Couchbase Capella environments.

    Describe your project, clusters, buckets and credentials in capella.yaml, then plan and apply.
    """
    try:
        td = parse_duration(timeout)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--timeout") from None
    setup_logging(log_level)
    set_quiet(quiet)
    ctx.obj = AppState(config_flag=config, profile_flag=profile, output=output, log_level=log_level,
                       auto_approve=auto_approve, quiet=quiet, no_wait=no_wait, timeout=td)


def _register() -> None:
    from capellactl.cli import configure, env, help, init, resource_cmds, sync

    for cmd in (help.help_cmd, help.completion, configure.configure, init.init, env.import_cmd, env.validate,
                env.plan, env.apply, sync.sync, env.destroy, env.drift):
        cli.add_command(cmd)
    for grp in resource_cmds.GROUPS:
        cli.add_command(grp)


_register()


def _utf8_streams() -> None:
    """Output uses characters such as → and ✔; a Windows pipe or file defaults to cp1252, which cannot encode them."""
    for stream in (sys.stdout, sys.stderr):
        if (getattr(stream, "encoding", "") or "").lower().replace("-", "") != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main() -> None:
    _utf8_streams()
    cli(prog_name="capellactl")
