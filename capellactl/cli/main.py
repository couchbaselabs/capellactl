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
    Conflict,
    Forbidden,
    NotFound,
    PreconditionFailed,
    RateLimited,
    ServerError,
    TransportError,
    Unauthorized,
    ValidationFailed,
)
from capellactl.cli.console import err, error, set_quiet, setup_logging
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


RETRY = "Run the command again; steps that already finished are not repeated."
# What to do about a Capella error that comes without a hint, by kind (CAP-063 AC2).
API_ACTIONS: list[tuple[type[CapellaApiError], str]] = [
    (NotFound, "It may have been deleted outside capellactl: run 'capellactl sync' to bring capella.yaml in line "
               "with Capella, then run the command again."),
    (Conflict, "Something else is changing it right now: wait until that finishes, then run the command again."),
    (PreconditionFailed, "It changed while capellactl was working on it: run the command again."),
    (ValidationFailed, "Change the value Capella names, then run the command again."),
    (RateLimited, "Capella is limiting requests: wait a minute, then run the command again."),
    (ServerError, f"Capella had an internal problem: wait a few minutes. {RETRY}"),
]


def api_error_exit(exc: CapellaApiError) -> CliExit:
    """[ERROR] is Capella's message, [ACTION] its hint, or the usual next step for that kind of error (CAP-063)."""
    if isinstance(exc, Unauthorized):
        msg = "Capella rejected the API Key Token" + (f": {exc.hint}" if exc.hint else "")
        return CliExit(ExitCode.ERROR, msg, topic="environment",
                       action="Check that CAPELLA_API_KEY (or your profile: 'capellactl configure show') holds the API "
                              "Key Token, not the API Key ID, and that this machine's public IP is in the key's allowed "
                              "IPs.")
    msg = f"Capella refused {exc.method} {exc.path} ({exc.http_status}): {exc.message}".rstrip(": ")
    if isinstance(exc, Forbidden):
        roles = required_roles(exc.method, exc.path)
        action = (f"Ask an Organization Owner to give the API key the {roles} role, then run the command again."
                  if roles else "Ask an Organization Owner for a role that allows this, then run the command again.")
        hint = f"{exc.hint.rstrip('.')}. " if exc.hint else ""
        return CliExit(ExitCode.ERROR, msg, topic="environment", action=hint + action)
    action = next((a for kind, a in API_ACTIONS if isinstance(exc, kind)), f"Check the value Capella names. {RETRY}")
    return CliExit(ExitCode.ERROR, msg, action=f"{exc.hint.rstrip('.')}. {RETRY}" if exc.hint else action)


class RootGroup(SuggestingGroup):
    """Turns every failure into a clean, redacted message and the right exit code."""

    def main(self, args: Any = None, prog_name: str | None = None, complete_var: str | None = None,
             standalone_mode: bool = True, **extra: Any) -> Any:
        """click's own errors (usage, bad values, Ctrl-C at a prompt) in the [ERROR]/[ACTION] form (CAP-063 AC5)."""
        if not standalone_mode:
            return super().main(args, prog_name, complete_var, False, **extra)
        try:
            rv = super().main(args, prog_name, complete_var, False, **extra)
        except click.UsageError as exc:
            path = exc.ctx.command_path if exc.ctx else "capellactl"
            if exc.ctx:
                err(exc.ctx.get_usage())
            error(exc.format_message(), f"Run '{path} --help' to see its commands, options and examples.")
            sys.exit(exc.exit_code)
        except click.ClickException as exc:
            error(exc.format_message(), "Run the command with --help to see what it expects.")
            sys.exit(exc.exit_code)
        except click.Abort:
            error("Aborted.", "Run the command again when you are ready.")
            sys.exit(int(ExitCode.ERROR))
        sys.exit(rv if isinstance(rv, int) else 0)

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
        except AmbiguousWriteError as exc:
            error(str(exc), "Run 'capellactl plan' to see whether Capella made the change, then run the command again "
                            "if it did not.")
            ctx.exit(int(ExitCode.ERROR))
        except TransportError as exc:
            error(f"Capella could not be reached: {exc}", "Check this machine's network connection and proxy "
                                                          f"settings. {RETRY}")
            ctx.exit(int(ExitCode.ERROR))
        except KeyboardInterrupt:
            error("Interrupted.", f"{RETRY} Run 'capellactl plan' to see what is left to do.")
            ctx.exit(int(ExitCode.INTERRUPTED))
        except (click.exceptions.Exit, click.exceptions.Abort, click.ClickException):
            raise
        except Exception as exc:  # noqa: BLE001 - last-resort handler, always redacted
            state = ctx.find_object(AppState)
            debug = bool(state and state.log_level == "debug")
            error(f"unexpected error: {redact(exc)}",
                  "Run the command again with --log-level debug, and report the output (secrets are masked) to the "
                  "capellactl maintainers." if not debug else "Report the output above (secrets are masked) to the "
                  "capellactl maintainers.")
            if debug:
                err(redact("".join(traceback.format_exception(exc))))
            ctx.exit(int(ExitCode.ERROR))
        return None


def _report(exc: CliExit) -> None:
    """[ERROR] for a failure, [WARNING] for a message on exit 0 or 2, then [ACTION] (CAP-063)."""
    if not exc.message:
        return
    from capellactl.cli.console import warning

    show = warning if exc.code in (ExitCode.OK, ExitCode.CHANGES) else error
    show(exc.message, exc.action, exc.topic)


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
