"""CAP-020 AC2/AC10: the API's schedule rules are checked offline by validate."""
from __future__ import annotations

import pytest

from tests.conftest import MINIMAL


def _hib(**days):
    lines = "".join(f"      {k}: {v}\n" for k, v in days.items())
    return MINIMAL + "    hibernation:\n" + lines


@pytest.mark.story("CAP-020", "AC2")
@pytest.mark.parametrize(("days", "message"), [
    ({"timezone": "US/Pacific", "weekdays": '"08:15-18:00"'}, "start minute must be 00 or 30 (got 08:15)"),
    ({"timezone": "US/Pacific", "weekdays": '"24:00-18:00"'}, "start hour must be 00–23 (got 24:00)"),
    ({"timezone": "US/Pacific", "weekdays": '"18:00-08:00"'}, "the on-window must start before it ends"),
    ({"timezone": "US/Pacific", "weekdays": '"off"', "weekend": '"off"'}, "cannot be off every day of the week"),
    ({"timezone": "America/Denver", "weekdays": '"08:00-18:00"'}, "timezone"),
    ({"timezone": "US/Pacific", "weekdays": '"on 08:00-18:00"'}, "weekdays"),
    ({"weekdays": '"08:00-18:00"'}, "timezone is required"),
])
def test_schedule_validate_ac2_rules(run, write_config, days, message):
    write_config(_hib(**days))
    r = run("validate")
    assert r.exit_code == 3, r.output
    assert message in r.output


@pytest.mark.story("CAP-020", "AC10")
def test_schedule_validate_ac10_quote_hint(run, write_config):
    write_config(_hib(timezone="US/Pacific", weekdays='"08:00-18:00"', weekend="off"))
    r = run("validate")
    assert r.exit_code == 0, r.output
    assert r.output.count('tip: quote "on"/"off" in hibernation to avoid YAML boolean conversion') == 1
