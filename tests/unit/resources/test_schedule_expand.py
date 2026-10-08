"""CAP-020 AC1/AC10: the friendly hibernation form expands to Capella's 7-day API form."""
from __future__ import annotations

import pytest

from capellactl.resources.schedule import expand

HIB = {"timezone": "US/Pacific", "weekdays": "08:00-18:00", "weekend": "off", "friday": "08:00-14:30"}


def _custom(day, fh, fm, th, tm):
    return {"day": day, "state": "custom", "from": {"hour": fh, "minute": fm}, "to": {"hour": th, "minute": tm}}


@pytest.mark.story("CAP-020", "AC1")
def test_schedule_expand_ac1_friendly_to_api():
    assert expand(HIB) == {"timezone": "US/Pacific", "days": [
        _custom("monday", 8, 0, 18, 0), _custom("tuesday", 8, 0, 18, 0), _custom("wednesday", 8, 0, 18, 0),
        _custom("thursday", 8, 0, 18, 0), _custom("friday", 8, 0, 14, 30),
        {"day": "saturday", "state": "off"}, {"day": "sunday", "state": "off"}]}


@pytest.mark.story("CAP-020", "AC1")
def test_schedule_expand_ac1_override_wins():
    days = {d["day"]: d for d in expand({**HIB, "wednesday": "on", "sunday": "10:00-12:00"})["days"]}
    assert days["wednesday"] == {"day": "wednesday", "state": "on"}
    assert days["sunday"] == _custom("sunday", 10, 0, 12, 0)
    assert days["saturday"] == {"day": "saturday", "state": "off"}


@pytest.mark.story("CAP-020", "AC1")
def test_schedule_expand_ac1_end_of_day_24_00():
    monday = expand({"timezone": "US/Pacific", "weekdays": "08:00-24:00", "weekend": "on"})["days"][0]
    assert monday == _custom("monday", 8, 0, 0, 0)


@pytest.mark.story("CAP-020", "AC10")
def test_schedule_expand_ac10_yaml_booleans():
    days = {d["day"]: d["state"] for d in expand({"timezone": "US/Pacific", "weekdays": True, "weekend": False})["days"]}
    assert days["monday"] == "on" and days["saturday"] == "off"
