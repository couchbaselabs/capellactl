"""CAP-018 AC7: every capellactl command in the migration guide exists, with the options it uses."""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import click
import pytest

from capellactl.cli.main import cli

GUIDE = Path(__file__).resolve().parents[3] / "docs" / "migrating-from-scale-script.md"


def _commands(text: str) -> list[list[str]]:
    lines = re.findall(r"`(capellactl [^`]+)`", text) + re.findall(r"^(capellactl .+)$", text, flags=re.M)
    return [shlex.split(line.split("#")[0])[1:] for line in lines if "--" in line or " " in line]


def _resolve(args: list[str]) -> tuple[click.Command, set[str]]:
    """The command an argument list runs, and every option name valid on its path."""
    cmd: click.Command = cli
    opts = {o for p in cli.params for o in p.opts + p.secondary_opts}
    for a in args:
        if a.startswith("-") or not isinstance(cmd, click.Group):
            continue
        sub = cmd.get_command(click.Context(cmd), a)
        if sub is None:
            continue
        cmd = sub
        opts |= {o for p in cmd.params for o in p.opts + p.secondary_opts}
    return cmd, opts


@pytest.mark.story("CAP-018", "AC7")
def test_docs_ac7_migration_guide_commands_valid(run):
    commands = _commands(GUIDE.read_text())
    assert len(commands) >= 5
    for args in commands:
        cmd, opts = _resolve(args)
        assert cmd is not cli, f"unknown command: {args}"
        for a in args:
            if a.startswith("-") and not re.fullmatch(r"[+-]\d+", a):
                assert a in opts, f"{a} is not an option of {' '.join(args)}"
        path = [a for a in args if not a.startswith("-") and not re.fullmatch(r"[+-]?\d+|CLUSTER|nova-dev-01|search|json",
                                                                          a)]
        assert run(*path, "--help").exit_code == 0, path


DOCS = [GUIDE.parents[0] / "getting-started.md", GUIDE.parents[0] / "release-1.0.0" / "cheatsheet.md",
        GUIDE.parents[1] / "README.md", *sorted((GUIDE.parents[1] / "capellactl" / "help").glob("*.md"))]


def _doc_lines() -> list[tuple[str, str]]:
    out = []
    for doc in DOCS:
        for block in re.findall(r"```bash\n(.*?)```", doc.read_text(), flags=re.S):
            for line in block.replace("\\\n", " ").splitlines():  # join continued lines
                line = line.strip()
                if not line.startswith("capellactl ") and "| capellactl " not in line:
                    continue  # only lines that run capellactl (not `cd capellactl`, comments …)
                cmd = line.split("capellactl ", 1)[1]
                cmd = re.sub(r"\s+#.*$", "", cmd).split(";")[0]
                cmd = re.sub(r"\$\([^)]*\)", "198.51.100.7", cmd)
                out.append((doc.name, re.sub(r"\$[A-Z_]+", "X", cmd)))
    return out


def test_docs_every_command_parses(run):
    """Each `capellactl …` line in the docs parses (global options before the command, real options only)."""
    lines = _doc_lines()
    assert len(lines) > 150
    bad = []
    for doc, cmd in lines:
        r = run(*shlex.split(cmd), "--help")
        if r.exit_code != 0:
            bad.append(f"{doc}: capellactl {cmd} → {r.output.strip().splitlines()[-1]}")
    assert not bad, "\n".join(bad)
