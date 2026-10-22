"""Terminal output helpers. Everything printed goes through redaction (CAP-008)."""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
from collections.abc import Callable, Iterator
from typing import Any

import click

from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.output.redact import RedactingFilter, redact

_line_open = False  # err_inline() left the stderr line unfinished (state line followed by progress dots)


class _Spinner:
    """Turns | / - \\ where the next progress dot will go, so a wait visibly moves between dots (terminals only)."""

    FRAMES = "|/-\\"
    INTERVAL = 0.15

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._shown = False  # a frame is on screen, the cursor just after it

    @staticmethod
    def wanted() -> bool:
        try:
            tty = sys.stderr.isatty()
        except (AttributeError, ValueError):
            return False
        return tty and os.environ.get("TERM") != "dumb" and not os.environ.get("CI")

    def _write(self, text: str) -> None:
        sys.stderr.write(text)
        sys.stderr.flush()

    def erase(self) -> None:
        """Remove the frame (call with the lock held) so the next text takes its place."""
        if self._shown:
            self._write("\b \b")
            self._shown = False

    def _run(self) -> None:
        i = 0
        while not self._stop.wait(self.INTERVAL):
            with self.lock:
                if self._stop.is_set():
                    return
                self.erase()
                self._write(self.FRAMES[i % len(self.FRAMES)])
                self._shown = True
            i += 1

    def start(self) -> None:
        if self._thread is None and self.wanted():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="capellactl-spinner", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._stop.set()
            self._thread.join()
            self._thread = None
        with self.lock:
            self.erase()


_spinner = _Spinner()


def _close_line() -> None:
    global _line_open
    if _line_open:
        _spinner.stop()
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


_quiet = False  # --quiet / CAPELLACTL_QUIET (CAP-042): no progress, hints or notes


def set_quiet(value: bool) -> None:
    global _quiet
    _quiet = value


def is_quiet() -> bool:
    return _quiet


def note(msg: Any = "") -> None:
    """Progress, hints and "previous version kept" notes on stderr; silent with --quiet."""
    if not _quiet:
        err(msg)


def err_inline(msg: Any) -> None:
    """Write to stderr without ending the line; the next out()/err() ends it first. Progress: silent with --quiet."""
    global _line_open
    if _quiet:
        return
    with _spinner.lock:
        _spinner.erase()
        click.echo(redact(msg), err=True, nl=False)
    _line_open = True
    _spinner.start()


def wait_progress(label: str) -> tuple[Callable[[str, float], None], Callable[[], None]]:
    """on_state/on_tick for wait_for_cluster: `  LABEL: STATE (time) ....` with a dot every 30s of waiting."""
    from capellactl.engine.clock import format_duration
    from capellactl.engine.waiter import TRANSITIONAL

    def on_state(state: str, elapsed: float) -> None:
        line = f"  {label}: {state} ({format_duration(elapsed)})"
        if state in TRANSITIONAL:
            err_inline(line + " ")
        else:
            note(line)

    return on_state, lambda: err_inline(".")


def is_interactive() -> bool:
    """True when a person can answer prompts. Tests patch this."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


# ------------------------------------------------- approval and questions (CAP-042)
# Every command asks through these helpers, never through click.confirm/click.prompt directly
# (tests/unit/cli/test_prompt_helpers.py checks this), so no command can wait for input without a terminal.

def refusal(state: Any, verb: str) -> CliExit:
    msg = f"refusing to {verb} without approval; pass --auto-approve"
    if str(state.env.get("CI", "")).lower() in ("true", "1"):
        msg += "\nadd --auto-approve to this pipeline step"
    return CliExit(ExitCode.ERROR, msg)


def confirm(state: Any, question: str, verb: str, notes: str | None = None) -> bool:
    """Approve a change: True with --auto-approve, else ask (notes are printed first). No terminal: refuse."""
    if state.auto_approve:
        return True
    if not is_interactive():
        raise refusal(state, verb)
    if notes:
        out(notes)
    return bool(click.confirm(question, default=False))


def confirm_typed(state: Any, label: str, verb: str, matches: str | Callable[[str], bool],
                  notes: str | None = None) -> bool:
    """Approve a delete by typing a name: True with --auto-approve or when the typed text matches."""
    if state.auto_approve:
        return True
    if not is_interactive():
        raise refusal(state, verb)
    if notes:
        out(notes)
    typed = str(click.prompt(label, default="", show_default=False))
    return matches(typed) if callable(matches) else typed.strip() == matches


def ask(label: str, default: Any = None, flag: str | None = None, **kwargs: Any) -> Any:
    """Ask a question. Without a terminal: the default, or exit 3 naming the flag that answers it."""
    if not is_interactive():
        if default is not None:
            return default
        raise CliExit(ExitCode.CONFIG_INVALID, f"missing {flag or label} (no terminal to ask; pass it on the "
                                               "command line)")
    return click.prompt(label, default=default, **kwargs)


def ask_yes_no(question: str, default: bool) -> bool:
    """A yes/no question that is not an approval. Without a terminal: the default."""
    if not is_interactive():
        return default
    return bool(click.confirm(question, default=default))


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
            _close_line()  # a warning while waiting starts on its own line, not after the progress dots
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
