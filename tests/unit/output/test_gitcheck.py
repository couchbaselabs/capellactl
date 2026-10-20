"""CAP-008 AC4: warn when the credentials directory is not git-ignored."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from capellactl.output.secrets_out import git_warning

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    d = tmp_path / ".capellactl" / "credentials"
    d.mkdir(parents=True)
    return d


@pytest.mark.story("CAP-008", "AC4")
def test_gitcheck_ac4_warns_when_not_ignored(tmp_path):
    d = _repo(tmp_path)
    assert git_warning(d) == f"warning: {d} is not git-ignored; add .capellactl/ to .gitignore"


@pytest.mark.story("CAP-008", "AC4")
def test_gitcheck_ac4_silent_when_ignored(tmp_path):
    d = _repo(tmp_path)
    (tmp_path / ".gitignore").write_text(".capellactl/\n", encoding="utf-8")
    assert git_warning(d) is None


@pytest.mark.story("CAP-008", "AC4")
def test_gitcheck_ac4_silent_outside_git(tmp_path):
    d = tmp_path / "creds"
    d.mkdir()
    assert git_warning(d) is None
