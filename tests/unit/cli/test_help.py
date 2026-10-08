"""CAP-034: help command and topics."""
from __future__ import annotations

import socket

import click
import pytest

from capellactl.cli.help import TOPICS
from capellactl.cli.main import cli


def _paths(cmd: click.Command, path=()):
    yield path
    if isinstance(cmd, click.Group):
        for name, sub in cmd.commands.items():
            yield from _paths(sub, path + (name,))


@pytest.mark.story("CAP-034", "AC1")
def test_help_ac1_root_help_contains_sections(run):
    r = run("help")
    assert r.exit_code == 0
    assert "Commands:" in r.output
    assert "Getting started:" in r.output and "5. capellactl apply" in r.output
    assert "Topics (capellactl help <topic>):" in r.output
    for t in TOPICS:
        assert t in r.output


@pytest.mark.story("CAP-034", "AC2")
def test_help_ac2_matches_dash_dash_help(run):
    for path in _paths(cli):
        if not path or path == ("help",):
            continue
        a = run("help", *path)
        b = run(*path, "--help")
        assert a.exit_code == 0 and b.exit_code == 0, path
        assert a.output == b.output, f"help {' '.join(path)} differs from --help"


@pytest.mark.story("CAP-034", "AC2")
def test_help_ac2_unknown_command_suggestion(run):
    r = run("cluster", "scael")
    assert r.exit_code == 2
    assert "unknown command 'scael'. Did you mean 'scale'?" in r.output
    r = run("help", "cluster", "scael")
    assert r.exit_code == 2 and "Did you mean 'scale'?" in r.output


@pytest.mark.story("CAP-034", "AC3")
def test_help_ac3_topics_listed(run):
    r = run("help", "topics")
    assert r.exit_code == 0
    assert len(TOPICS) == 9
    for name, summary in TOPICS.items():
        assert name in r.output and summary in r.output


@pytest.mark.story("CAP-034", "AC3")
def test_help_ac3_topic_plain_when_not_tty(run):
    for t in TOPICS:
        r = run("help", t)
        assert r.exit_code == 0, t
        assert "\x1b[" not in r.output
    assert "Scale out" in run("help", "scaling").output


@pytest.mark.story("CAP-034", "AC3")
def test_help_ac3_unknown_topic(run):
    r = run("help", "scalling")
    assert r.exit_code == 2
    assert "Did you mean 'scaling'?" in r.output and "getting-started" in r.output


@pytest.mark.story("CAP-034", "AC7")
def test_help_ac7_offline_no_key(run, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    for args in (("help",), ("help", "topics"), ("help", "safety"), ("help", "config"),
                 ("help", "config", "clusters.name"), ("completion", "bash")):
        r = run(*args, no_env=True)
        assert r.exit_code == 0, args
