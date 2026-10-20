"""CAP-033 AC4: the runbook covers the day-2 tasks, each with the exact command and the expected output."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RUNBOOK = Path(__file__).resolve().parents[3] / "docs" / "runbook.md"
TASKS = {
    "Scale out": "cluster scale", "Scale in": "cluster scale", "Scale up": "cluster update",
    "Power off and on": "cluster power", "Set up a hibernation schedule": "cluster schedule set",
    "Pause and resume the schedule": "cluster schedule pause", "Add a bucket": "bucket create",
    "Add a collection": "collection create", "Add an app credential": "credential create",
    "Rotate a password": "--rotate-password", "Add an office IP": "cidr create",
    "Recover from deploymentFailed": "cluster delete", "Tear down": "destroy",
}


@pytest.mark.story("CAP-033", "AC4")
def test_docs_ac4_runbook_sections():
    text = RUNBOOK.read_text(encoding="utf-8")
    sections = dict(re.findall(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, flags=re.S | re.M))
    for heading, command in TASKS.items():
        assert heading in sections, f"no '## {heading}' section"
        body = sections[heading]
        commands = "\n".join(re.findall(r"```bash\n(.*?)```", body, flags=re.S))
        assert f"capellactl {command}" in commands or command in commands, f"{heading}: no `{command}` command"
        assert "```text\n" in body, f"{heading}: no expected output"
