"""The spinner between progress dots: turns where the next dot goes, on terminals only."""
from __future__ import annotations

import io
import time

import pytest

from capellactl.cli import console


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def tty(monkeypatch):
    """A terminal on stderr. Installed by calling it inside the test: pytest's capture replaces sys.stderr after setup."""
    monkeypatch.setattr(console._Spinner, "INTERVAL", 0.01)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.setattr(console, "_quiet", False)

    def install() -> _Tty:
        stream = _Tty()
        monkeypatch.setattr("sys.stderr", stream)
        return stream

    yield install
    console._close_line()


def _rendered(raw: str) -> str:
    """What the terminal shows: each backspace moves back one place, the next character overwrites."""
    line: list[str] = []
    pos = 0
    for ch in raw:
        if ch == "\b":
            pos -= 1
        elif ch == "\n":
            line.append("\n")
            pos = len(line)
        else:
            if pos < len(line):
                line[pos] = ch
            else:
                line.append(ch)
            pos += 1
    return "".join(line)


@pytest.mark.story("CAP-007", "AC9")
def test_spinner_turns_between_dots_and_leaves_only_the_dots(tty):
    tty = tty()
    console.err_inline("  cluster try-01: deploying (0s) ")
    time.sleep(0.1)
    console.err_inline(".")
    time.sleep(0.1)
    console.note("  cluster try-01: healthy (1m21s)")
    raw = tty.getvalue()
    assert set(console._Spinner.FRAMES) <= set(raw)  # it turned
    assert _rendered(raw).replace(" \n", "\n") == ("  cluster try-01: deploying (0s) .\n"
                                                    "  cluster try-01: healthy (1m21s)\n")
    assert console._spinner._thread is None  # stopped with the line


@pytest.mark.story("CAP-007", "AC9")
@pytest.mark.parametrize("env", [{"CI": "true"}, {"TERM": "dumb"}])
def test_no_spinner_in_ci_or_dumb_terminals(tty, monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    tty = tty()
    console.err_inline("  cluster try-01: deploying (0s) ")
    time.sleep(0.05)
    assert tty.getvalue() == "  cluster try-01: deploying (0s) "


@pytest.mark.story("CAP-007", "AC9")
def test_no_spinner_when_stderr_is_not_a_terminal(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr("sys.stderr", stream)
    monkeypatch.setattr(console, "_quiet", False)
    console.err_inline("  cluster try-01: deploying (0s) ")
    time.sleep(0.05)
    console._close_line()
    assert stream.getvalue() == "  cluster try-01: deploying (0s) \n"
