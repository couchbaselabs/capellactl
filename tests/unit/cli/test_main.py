"""CAP-001: package scaffold and CLI skeleton."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click
import pytest

from capellactl import __version__
from capellactl.cli.main import cli

GROUPS = {"help", "completion", "configure", "init", "import", "sync", "validate", "plan", "apply", "destroy", "drift",
          "project", "cluster", "cidr", "bucket", "scope", "collection", "credential"}


def _walk(cmd: click.Command, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], click.Command]]:
    out = [(path, cmd)]
    if isinstance(cmd, click.Group):
        for name, sub in cmd.commands.items():
            out += _walk(sub, path + (name,))
    return out


@pytest.mark.story("CAP-001", "AC1")
def test_cli_ac1_version_output(run):
    r = run("--version")
    assert r.exit_code == 0
    assert r.output.splitlines()[0] == f"capellactl {__version__} (Management API v4.0)"


@pytest.mark.story("CAP-001", "AC2")
def test_cli_ac2_root_lists_all_groups(run):
    r = run("--help")
    assert r.exit_code == 0
    assert set(cli.commands) == GROUPS
    for g in GROUPS:
        assert f"  {g} " in r.output or f"  {g}\n" in r.output


@pytest.mark.story("CAP-001", "AC2")
def test_cli_ac2_every_group_has_examples(run):
    for path, cmd in _walk(cli):
        if isinstance(cmd, click.Group) or not path:
            r = run(*path, "--help")
            assert r.exit_code == 0, path
            assert "Examples:" in r.output, f"{' '.join(path) or 'root'} --help has no Examples"


@pytest.mark.story("CAP-001", "AC3")
@pytest.mark.parametrize("flags", [
    ["-c", "x.yaml"], ["--profile", "dev"], ["-o", "json"], ["--log-level", "debug"], ["--auto-approve"],
    ["--no-wait"], ["--timeout", "5m"],
])
def test_cli_ac3_global_flags_reach_context(flags):
    from click.testing import CliRunner

    from capellactl.cli.state import AppState

    seen = {}

    @cli.command("probe-ctx", hidden=True)
    @click.pass_obj
    def probe(obj: AppState) -> None:
        seen["state"] = obj

    try:
        r = CliRunner().invoke(cli, [*flags, "probe-ctx"], catch_exceptions=False)
    finally:
        cli.commands.pop("probe-ctx")
    assert r.exit_code == 0, r.output
    s = seen["state"]
    expected = {"-c": ("config_flag", "x.yaml"), "--profile": ("profile_flag", "dev"), "-o": ("output", "json"),
                "--log-level": ("log_level", "debug"), "--auto-approve": ("auto_approve", True),
                "--no-wait": ("no_wait", True)}
    if flags[0] == "--timeout":
        assert s.timeout.total_seconds() == 300
    else:
        attr, value = expected[flags[0]]
        assert getattr(s, attr) == value


@pytest.mark.story("CAP-001", "AC3")
def test_cli_ac3_invalid_output_format(run):
    r = run("-o", "yaml", "validate")
    assert r.exit_code == 2
    assert "text" in r.output and "json" in r.output


def test_cli_output_survives_a_non_utf8_pipe():
    """A Windows pipe or redirect defaults to cp1252, which has no → (used by `help topics`)."""
    root = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONPATH": str(root)}
    r = subprocess.run([sys.executable, "-m", "capellactl", "help", "topics"], env=env, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert "→" in r.stdout.decode("utf-8")
