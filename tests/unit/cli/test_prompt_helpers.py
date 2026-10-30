"""CAP-042 AC6: every command asks through the console helpers, and every write command accepts approval."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from capellactl.cli import console
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.cli.state import AppState

CLI = Path(__file__).resolve().parents[3] / "capellactl" / "cli"


def _direct_prompts(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and node.attr in ("confirm", "prompt") \
                and isinstance(node.value, ast.Name) and node.value.id == "click":
            found.append(f"{path.name}:{node.lineno} click.{node.attr}")
        if isinstance(node, ast.ImportFrom) and node.module == "click" \
                and any(a.name in ("confirm", "prompt") for a in node.names):
            found.append(f"{path.name}:{node.lineno} from click import …")
    return found


@pytest.mark.story("CAP-042", "AC6")
def test_ci_ac6_no_direct_prompts():
    modules = [p for p in CLI.glob("*.py") if p.name != "console.py"]
    assert len(modules) > 10
    found = [f for p in modules for f in _direct_prompts(p)]
    assert not found, "ask through capellactl.cli.console instead:\n" + "\n".join(found)


@pytest.mark.story("CAP-042", "AC6")
def test_ci_ac6_write_commands_accept_approval():
    """Approval is a global flag, so every command accepts it; it must stay global and keep its aliases."""
    from capellactl.cli.main import cli

    opts = {o for p in cli.params for o in p.opts}
    assert {"--auto-approve", "--yes", "-y", "--quiet", "-q"} <= opts


@pytest.mark.story("CAP-042", "AC2")
def test_ci_ac2_ask_uses_default_or_names_flag(monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: False)
    assert console.ask("Memory (MB)", 1024, flag="--memory") == 1024
    assert console.ask_yes_no("Overwrite?", False) is False
    with pytest.raises(CliExit) as exc:
        console.ask("Memory (MB)", flag="--memory")
    assert exc.value.code == ExitCode.CONFIG_INVALID
    assert exc.value.message == "missing --memory: there is no terminal to ask for it"
    assert exc.value.action == "Give it on the command line: --memory VALUE."


@pytest.mark.story("CAP-042", "AC3")
def test_ci_ac3_refusal_message(monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: False)
    state = AppState(env={})
    with pytest.raises(CliExit) as exc:
        console.confirm(state, "Delete it?", "delete a bucket")
    assert exc.value.code == ExitCode.ERROR
    assert exc.value.message == "refusing to delete a bucket without approval: there is no terminal to ask"
    assert exc.value.action.startswith("Add --auto-approve")
    state = AppState(env={"CI": "true", "CAPELLACTL_AUTO_APPROVE": "true"})
    with pytest.raises(CliExit) as exc:
        console.confirm_typed(state, "Type the name", "delete a bucket", "orders")
    assert exc.value.action == "Add --auto-approve to this pipeline step."
    assert console.confirm(AppState(auto_approve=True, env={}), "Delete it?", "delete a bucket") is True
