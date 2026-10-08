"""CAP-003 AC6: CLI prints message and hint."""
from __future__ import annotations

import pytest


@pytest.mark.story("CAP-003", "AC6")
def test_cli_ac6_prints_message_and_hint(fake, run, write_config):
    fake.seed_project("nova-dev", description="Nova development environment")
    fake.fail_next("POST", "*/clusters", 422, code=4001)
    write_config()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 1
    assert "Failed: cluster nova-dev-01" in r.output
    assert "Hint: injected 422" in r.output
