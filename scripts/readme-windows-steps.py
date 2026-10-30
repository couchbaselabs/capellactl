#!/usr/bin/env python3
"""Turn the README's Windows install table into a PowerShell script for CI (CAP-055 AC3).

    python scripts/readme-windows-steps.py --source DIR --workdir DIR --out steps.ps1 [--python PATH]

The commands come from the table between <!-- windows-install:start --> and <!-- windows-install:end -->, so a
change to the README changes what CI runs. CI differs from a customer's laptop in three places only:
- step 1 (`winget install`) is skipped: the runner already has Git and Python;
- `git clone` clones the checked-out commit (`--source`) instead of GitHub's main branch;
- `Set-ExecutionPolicy -Scope CurrentUser` becomes `-Scope Process … -Force`: no prompt, and the runner's settings
  are left alone. The script first sets the process policy to Restricted, as on a new Windows laptop, so
  `Activate.ps1` only runs if the README's policy step works.
`--python PATH` replaces `py -3.12`, for runners where the py launcher does not list setup-python's interpreter.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
START, END = "<!-- windows-install:start -->", "<!-- windows-install:end -->"
CLONE_URL = "https://github.com/couchbaselabs/capellactl.git"


def steps(readme: str) -> list[tuple[str, list[str]]]:
    """Each table row as (step label, its commands in order)."""
    if START not in readme or END not in readme:
        raise ValueError(f"README has no {START} … {END} table")
    out = []
    for line in readme[readme.index(START) + len(START):readme.index(END)].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not re.match(r"\d+\.", cells[0]):
            continue
        out.append((cells[0], re.findall(r"`([^`]+)`", cells[1])))
    return out


def ci_commands(table: list[tuple[str, list[str]]], source: str, python: str | None = None) -> list[str]:
    cmds = []
    for _, commands in table:
        if commands and all(c.startswith("winget ") for c in commands):
            continue
        for c in commands:
            c = c.replace(CLONE_URL, f'"{source}" capellactl')
            c = c.replace("-Scope CurrentUser RemoteSigned", "-Scope Process RemoteSigned -Force")
            if python:
                c = c.replace("py -3.12", f'& "{python}"')
            cmds.append(c)
    return cmds


def ci_script(commands: list[str], workdir: str) -> str:
    lines = ["Set-ExecutionPolicy -Scope Process Restricted -Force   # as on a new Windows laptop",
             f'Set-Location (New-Item -ItemType Directory -Force "{workdir}")']
    for c in commands:
        quoted = c.replace("'", "''")
        lines += [f"Write-Host '> {quoted}'", "$global:LASTEXITCODE = 0", c,
                  f"if (-not $? -or $LASTEXITCODE) {{ Write-Host 'README step failed: {quoted}'; exit 1 }}"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True, help="checkout to clone instead of GitHub")
    ap.add_argument("--workdir", required=True, help="empty folder to run the steps in")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--python", help="interpreter to use instead of `py -3.12`")
    a = ap.parse_args()
    commands = ci_commands(steps(README.read_text(encoding="utf-8")), a.source, a.python)
    a.out.write_text(ci_script(commands, a.workdir), encoding="utf-8-sig")   # BOM: Windows PowerShell reads UTF-8
    print(f"{a.out}: {len(commands)} README commands")
    return 0


if __name__ == "__main__":
    sys.exit(main())
