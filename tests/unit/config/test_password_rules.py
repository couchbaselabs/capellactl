"""CAP-028 AC3: configured passwords are checked offline; the value is never shown."""
from __future__ import annotations

import textwrap

import pytest

from capellactl.config.loader import ConfigError, load_config
from tests.conftest import MINIMAL, assert_no_secret, seed_healthy
from tests.scenario.helpers import ORDERS_APP, ORDERS_BUCKET

MESSAGE = "password for orders_app does not meet Capella rules (min 8, upper, lower, digit, special, none of < > ; . * & | £)"


@pytest.mark.story("CAP-028", "AC3")
def test_rotation_ac3_weak_password_rejected(tmp_path, run, fake):
    seed_healthy(fake)
    p = tmp_path / "capella.yaml"
    p.write_text(textwrap.dedent(MINIMAL) + ORDERS_BUCKET + ORDERS_APP, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(p, env={"CAPELLA_ORG_ID": "org-1", "ORDERS_APP_PASSWORD": "short"})
    assert f"credential orders_app › password (line 28)\n    {MESSAGE}" in str(exc.value)
    for args in (("validate",), ("--auto-approve", "credential", "update", "nova-dev-01", "orders_app",
                                 "--rotate-password")):
        r = run(*args, extra_env={"ORDERS_APP_PASSWORD": "short1"})
        assert r.exit_code == 3, r.output
        assert MESSAGE in r.output
        assert_no_secret(r.output, "short1")
    assert fake.writes() == []


@pytest.mark.story("CAP-028", "AC3")
@pytest.mark.parametrize("args", [("credential",), ("credential", "create"), ("credential", "update")])
def test_rotation_ac3_help_lists_rules(run, args):
    r = run(*args, "--help")
    assert r.exit_code == 0, r.output
    assert "Password rules (Capella; checked before anything is sent):" in r.output
    assert "at least 8 characters" in r.output and "one special character" in r.output
    assert "none of these characters: < > ; . * & | £" in r.output
