"""CAP-034 AC6: shell completion."""
from __future__ import annotations

import pytest
from click.shell_completion import ShellComplete

from capellactl.cli.main import cli
from tests.conftest import MINIMAL


@pytest.mark.story("CAP-034", "AC6")
@pytest.mark.parametrize("shell,marker", [("bash", "complete -o"), ("zsh", "compdef"), ("fish", "complete --no-files")])
def test_completion_ac6_scripts_generated(run, shell, marker):
    r = run("completion", shell)
    assert r.exit_code == 0
    assert "_CAPELLACTL_COMPLETE" in r.output and marker in r.output


def _complete(args: list[str], incomplete: str) -> list[str]:
    comp = ShellComplete(cli, {}, "capellactl", "_CAPELLACTL_COMPLETE")
    return [c.value for c in comp.get_completions(args, incomplete)]


@pytest.mark.story("CAP-034", "AC6")
def test_completion_ac6_commands(write_config):
    assert "cluster" in _complete([], "clu")


@pytest.mark.story("CAP-034", "AC6")
def test_completion_ac6_cluster_names_from_config(write_config):
    write_config(MINIMAL)
    assert _complete(["cluster", "get"], "nova") == ["nova-dev-01"]
    assert _complete(["cluster", "scale"], "") == ["nova-dev-01"]
