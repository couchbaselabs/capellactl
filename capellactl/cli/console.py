"""Terminal output helpers. Everything printed goes through redaction (CAP-008)."""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Callable, Iterator
from typing import Any

import click

from capellactl.output.redact import RedactingFilter, redact

_line_open = False  # err_inline() left the stderr line unfinished (state line followed by progress dots)


def _close_line() -> None:
    global _line_open
    if _line_open:
        click.echo("", err=True)
        _line_open = False


_muted = False  # muted(): commands that print one JSON document silence the usual text output


@contextlib.contextmanager
def muted() -> Iterator[None]:
    global _muted
    before, _muted = _muted, True
    try:
        yield
    finally:
        _muted = before


def out(msg: Any = "") -> None:
    if _muted:
        return
    _close_line()
    click.echo(redact(msg))


def emit(msg: Any) -> None:
    """stdout even while muted (the JSON document itself)."""
    _close_line()
    click.echo(redact(msg))


def err(msg: Any = "") -> None:
    _close_line()
    click.echo(redact(msg), err=True)


def err_inline(msg: Any) -> None:
    """Write to stderr without ending the line; the next out()/err() ends it first."""
    global _line_open
    click.echo(redact(msg), err=True, nl=False)
    _line_open = True


def wait_progress(label: str) -> tuple[Callable[[str, float], None], Callable[[], None]]:
    """on_state/on_tick for wait_for_cluster: `  LABEL: STATE (time) ....` with a dot every 30s of waiting."""
    from capellactl.engine.clock import format_duration
    from capellactl.engine.waiter import TRANSITIONAL

    def on_state(state: str, elapsed: float) -> None:
        line = f"  {label}: {state} ({format_duration(elapsed)})"
        if state in TRANSITIONAL:
            err_inline(line + " ")
        else:
            err(line)

    return on_state, lambda: err_inline(".")


def is_interactive() -> bool:
    """True when a person can answer prompts. Tests patch this."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def stdout_is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


_HANDLER_NAME = "capellactl-stderr"


class _ClickStderrHandler(logging.Handler):
    """Writes through click so CliRunner and real terminals both capture it on stderr."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            click.echo(redact(self.format(record)), err=True)
        except Exception:  # noqa: BLE001
            self.handleError(record)


def setup_logging(level: str) -> None:
    logger = logging.getLogger("capellactl")
    for h in list(logger.handlers):
        if h.get_name() == _HANDLER_NAME:
            logger.removeHandler(h)
    handler = _ClickStderrHandler()
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    logger.setLevel({"error": logging.ERROR, "warn": logging.WARNING, "info": logging.INFO,
                     "debug": logging.DEBUG}[level])
    logger.propagate = True
