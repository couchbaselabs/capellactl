"""CAP-055: the Windows install table and the PowerShell translations work in Windows PowerShell 5.1."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.integration.harness import load_script

steps_script = load_script("readme-windows-steps")
ROOT = Path(__file__).resolve().parents[3]
README = (ROOT / "README.md").read_text(encoding="utf-8")
GUIDE = (ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8")
CI_HELP = (ROOT / "capellactl" / "help" / "ci.md").read_text(encoding="utf-8")
DOWNLOADS = (ROOT / "downloads" / "README.md").read_text(encoding="utf-8")

# Syntax that only bash/zsh understand, or that means something else in Windows PowerShell 5.1.
BASH_ONLY = {
    "&&": r"&&", "||": r"\|\|", "export": r"(^|;\s*)export ", "source": r"(^|;\s*)source ", ".venv/bin": r"\.venv/bin",
    "trailing \\": r"\\\s*$", "pbpaste": r"\bpbpaste\b", "python3": r"\bpython3\b", "bare curl": r"(?<![\w.])curl ",
    "$?": r"\$\?",
}


def _between(text: str, name: str) -> str:
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    assert start in text and end in text, f"missing {start} … {end}"
    return text[text.index(start) + len(start):text.index(end)]


def _rows(table: str) -> list[list[str]]:
    rows = []
    for line in table.strip().splitlines()[2:]:                       # skip the header and the |---| line
        cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
        rows.append([c.strip().replace("\\|", "|") for c in cells])
    return rows


def _code(cell: str) -> list[str]:
    """The code spans in a table cell: ``a`b`` and `a`."""
    return [a or b for a, b in re.findall(r"``\s?(.+?)\s?``|`([^`]+)`", cell)]


def _bash_only(command: str) -> list[str]:
    return [name for name, pat in BASH_ONLY.items() if re.search(pat, command)]


def _powershell_commands() -> list[str]:
    cmds = [c for _, commands in steps_script.steps(README) for c in commands]
    cmds += [c for row in _rows(_between(GUIDE, "powershell-translation")) for c in _code(row[1])]
    cmds += [line for block in re.findall(r"```powershell\n(.*?)```", DOWNLOADS, flags=re.S)
             for line in block.splitlines() if line and not line.startswith("#")]
    cmds += [line.split("run:", 1)[1] for line in CI_HELP.splitlines() if "LASTEXITCODE" in line]
    return cmds


@pytest.mark.story("CAP-055", "AC1")
def test_windows_docs_ac1_readme_install_table():
    install = README[README.index("## Install"):README.index("## Quick start")]
    assert "### On Windows (PowerShell)" in install and "<!-- windows-install:start -->" in install
    table = steps_script.steps(README)
    commands = [c for _, cmds in table for c in cmds]
    for expected in ("winget install --id Python.Python.3.12 -e", "py -3.12 --version", "py -3.12 -m venv .venv",
                     r".venv\Scripts\python -m pip install -e .", "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned",
                     r".venv\Scripts\Activate.ps1", "capellactl --version", r"mkdir ~\capella-env"):
        assert expected in commands, expected
    assert [label.split(".")[0] for label, _ in table] == [str(n) for n in range(1, len(table) + 1)]
    for row in _rows(_between(README, "windows-install")):
        assert len(row) == 3 and row[2], f"step {row[0]} says nothing about what to expect"
    help_text = " ".join(row[2] for row in _rows(_between(README, "windows-install")))
    for failure in ("requires a different Python", "Microsoft Store", "&&", "company blocks", "is not recognized"):
        assert failure in help_text, failure


@pytest.mark.story("CAP-055", "AC2")
@pytest.mark.parametrize("bad,name", [
    ("git clone https://x/y.git && cd y", "&&"), ("export PW='x'", "export"), ("source .venv/bin/activate", "source"),
    (".venv/bin/pip install -e .", ".venv/bin"), ("capellactl cluster create a \\", "trailing \\"),
    ("pbpaste", "pbpaste"), ("python3 -m venv .venv", "python3"), ("curl -s https://checkip.amazonaws.com", "bare curl"),
    ("capellactl plan || [ $? -eq 2 ]", "||"),
])
def test_windows_docs_ac2_bash_only_syntax_is_caught(bad, name):
    assert name in _bash_only(bad)


@pytest.mark.story("CAP-055", "AC2")
def test_windows_docs_ac2_no_bash_only_syntax():
    commands = _powershell_commands()
    assert len(commands) >= 20
    bad = {c: _bash_only(c) for c in commands if _bash_only(c)}
    assert not bad, f"bash-only syntax in Windows commands: {bad}"


@pytest.mark.story("CAP-055", "AC6")
def test_windows_docs_ac6_exe_on_user_path():
    downloads = load_script("update-downloads")
    generated = downloads.downloads_readme(None)
    assert generated == DOWNLOADS                                      # what update-downloads.py --check compares
    block = generated[generated.index("To type `capellactl` from any folder"):]
    assert r"$env:LOCALAPPDATA\Programs\capellactl\capellactl.exe" in block
    assert "SetEnvironmentVariable('Path', \"$userPath;" in block and "'User')" in block
    assert "Machine" not in block and "administrator rights" in block


@pytest.mark.story("CAP-055", "AC3")
def test_windows_docs_ac3_steps_extracted_from_readme():
    table = steps_script.steps(README)
    cmds = steps_script.ci_commands(table, r"D:\a\capellactl")
    readme_cmds = [c for _, commands in table[1:] for c in commands]           # all but step 1 (winget)
    assert len(cmds) == len(readme_cmds) and not any(c.startswith("winget") for c in cmds)
    assert cmds[1] == r'git clone "D:\a\capellactl" capellactl' and cmds[2] == "cd capellactl"
    assert "Set-ExecutionPolicy -Scope Process RemoteSigned -Force" in cmds
    assert [c for c in cmds if "git clone" not in c and "Set-ExecutionPolicy" not in c] == \
           [c for c in readme_cmds if "git clone" not in c and "Set-ExecutionPolicy" not in c]
    with_py = steps_script.ci_commands(table, "src", python=r"C:\py\python.exe")
    assert r'& "C:\py\python.exe" -m venv .venv' in with_py and not any("py -3.12" in c for c in with_py)

    script = steps_script.ci_script(cmds, r"C:\work")
    assert script.splitlines()[0].startswith("Set-ExecutionPolicy -Scope Process Restricted -Force")
    assert script.count("README step failed") == len(cmds)


@pytest.mark.story("CAP-055", "AC3")
def test_windows_docs_ac3_ci_runs_the_readme_in_windows_powershell():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci[ci.index("  windows-install:"):ci.index("  image-smoke:")]
    assert "runs-on: windows-latest" in job and "shell: powershell" in job
    assert "scripts/readme-windows-steps.py" in job and "powershell -NoProfile" in job


def _shell_lines() -> list[str]:
    quick_start = README[README.index("## Quick start"):README.index("## Commands")]
    texts = [quick_start, GUIDE[GUIDE.index("## Step by step"):]] + [
        (ROOT / "docs" / f).read_text(encoding="utf-8") for f in ("runbook.md", "custom-clusters.md",
                                                                  "backup-restore.md")]
    lines = [line for t in texts for b in re.findall(r"```(?:bash|sh|shell)?\n(.*?)```", t, flags=re.S)
             for line in b.splitlines()]
    return lines + [line.split("run:", 1)[1] for line in CI_HELP.splitlines() if "run:" in line]


@pytest.mark.story("CAP-055", "AC5")
def test_windows_docs_ac5_translation_table_complete():
    left = " ".join(row[0] for row in _rows(_between(GUIDE, "powershell-translation")))
    # What the table's left column must show for each construct, once the docs use it.
    covers = {"&&": "&&", "||": "||", "export": "export ", "trailing \\": "ending in `\\`", "pbpaste": "pbpaste",
              "bare curl": "curl -s", "$?": "$?"}
    used = {name for line in _shell_lines() for name in _bash_only(line.split(" #")[0]) if name != "python3"}
    assert {"export", "trailing \\", "bare curl"} <= used          # the scan sees the docs' real commands
    assert used <= covers.keys(), f"no PowerShell translation for {used - covers.keys()}"
    missing = [name for name in used if covers[name] not in left]
    assert not missing, f"getting-started 'Using the commands in PowerShell' lacks a row for {missing}"
