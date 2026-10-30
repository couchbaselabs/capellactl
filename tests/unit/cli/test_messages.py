"""CAP-063: every error says what happened ([ERROR]) and what to do ([ACTION])."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from capellactl.api.errors import (
    CapellaApiError,
    Conflict,
    Forbidden,
    NotFound,
    RateLimited,
    ServerError,
    Unauthorized,
    ValidationFailed,
)
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.main import _report, api_error_exit

ROOT = Path(__file__).resolve().parents[3] / "capellactl"


@pytest.mark.story("CAP-063", "AC1")
def test_messages_ac1_cli_exit_format(capsys):
    _report(CliExit(ExitCode.CONFIG_INVALID, "nothing to do: neither --on nor --off was given", topic="hibernation",
                    action="Add --on to turn the cluster on, or --off to turn it off."))
    _report(CliExit(ExitCode.CHANGES, "capella.yaml is out of sync with Capella; nothing was written",
                    action="Run 'capellactl sync' to update it."))
    assert capsys.readouterr().err.splitlines() == [
        "[ERROR]: nothing to do: neither --on nor --off was given",
        "[ACTION]: Add --on to turn the cluster on, or --off to turn it off. See 'capellactl help hibernation'.",
        "[WARNING]: capella.yaml is out of sync with Capella; nothing was written",
        "[ACTION]: Run 'capellactl sync' to update it.",
    ]


def _cli_exits_without_action() -> list[str]:
    """CliExit(...) calls that give a message but no action=; an empty message ("") only sets the exit code."""
    found = []
    for path in sorted(ROOT.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "CliExit"):
                continue
            message = node.args[1] if len(node.args) > 1 else None
            empty = message is None or (isinstance(message, ast.Constant) and message.value == "")
            if not empty and not any(k.arg == "action" for k in node.keywords):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


@pytest.mark.story("CAP-063", "AC1")
def test_messages_ac1_every_cli_exit_has_action():
    assert _cli_exits_without_action() == []


@pytest.mark.story("CAP-063", "AC2")
@pytest.mark.parametrize("exc,error,action", [
    (Unauthorized(401, "Unauthorized", method="GET", path="/v4/organizations"),
     "Capella rejected the API Key Token", "holds the API Key Token, not the API Key ID"),
    (Forbidden(403, "Access denied", method="GET", path="/v4/organizations/o/projects/p/clusters"),
     "Capella refused GET /v4/organizations/o/projects/p/clusters (403): Access denied",
     "Ask an Organization Owner to give the API key the Organization Owner, Project Owner or Project Manager role"),
    (NotFound(404, "Not found", method="GET", path="/x"), "(404): Not found", "run 'capellactl sync'"),
    (Conflict(409, "Busy", method="PUT", path="/x"), "(409): Busy", "wait until that finishes"),
    (ValidationFailed(422, "Bad value", method="POST", path="/x"), "(422): Bad value", "Change the value Capella names"),
    (RateLimited(429, "Slow down", method="GET", path="/x"), "(429): Slow down", "wait a minute"),
    (ServerError(500, "Oops", method="GET", path="/x"), "(500): Oops", "Capella had an internal problem"),
    (ValidationFailed(422, "Bad region", hint="Use a region the provider offers.", method="POST", path="/x"),
     "(422): Bad region", "Use a region the provider offers. Run the command again"),
])
def test_messages_ac2_api_errors(capsys, exc: CapellaApiError, error, action):
    _report(api_error_exit(exc))
    err, act = capsys.readouterr().err.splitlines()[:2]
    assert err.startswith("[ERROR]: ") and error in err, err
    assert act.startswith("[ACTION]: ") and action in act, act


@pytest.mark.story("CAP-063", "AC2")
def test_messages_ac2_transport_and_unexpected(fake, run, write_config, monkeypatch):
    from capellactl.api.errors import TransportError

    write_config()
    for exc, error, action in [
        (TransportError("connection refused"), "[ERROR]: Capella could not be reached: connection refused",
         "[ACTION]: Check this machine's network connection and proxy settings."),
        (RuntimeError("boom"), "[ERROR]: unexpected error: boom", "[ACTION]: Run the command again with --log-level "
                                                                  "debug"),
    ]:
        def fail(*_a, _exc=exc, **_k):
            raise _exc
        monkeypatch.setattr("capellactl.cli.env.build_plan", fail)
        r = run("plan")
        assert r.exit_code == 1 and error in r.output and action in r.output, r.output
        assert "Error:" not in r.output


def _help_texts():
    import click

    from capellactl.cli.main import cli

    def walk(cmd, path):
        yield path, cmd
        if isinstance(cmd, click.Group):
            for name, sub in cmd.commands.items():
                yield from walk(sub, [*path, name])

    for path, cmd in walk(cli, ["capellactl"]):
        yield " ".join(path), cmd.get_help(click.Context(cmd, info_name=" ".join(path)))


def _story_ids_in_strings() -> list[str]:
    """String literals that may reach the user: not docstrings, not a reconciler's `story = "CAP-…"` tag."""
    import re

    found = []
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant):
                skip.add(id(body[0].value))
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "story" for t in node.targets):
                skip.add(id(node.value))
        found += [f"{path.relative_to(ROOT)}:{n.lineno}" for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip
                  and re.search(r"CAP-\d+", n.value)]
    return found


@pytest.mark.story("CAP-063", "AC7")
def test_messages_ac7_no_story_ids_shown():
    """Story numbers are for the people who build capellactl; help, messages and the schema never show them."""
    import re

    assert [path for path, text in _help_texts() if re.search(r"CAP-\d+", text)] == []
    assert _story_ids_in_strings() == []
    assert "CAP-" not in (ROOT / "config" / "schema.json").read_text(encoding="utf-8")
    assert not [p.name for p in (ROOT / "help").glob("*.md") if "CAP-" in p.read_text(encoding="utf-8")]
