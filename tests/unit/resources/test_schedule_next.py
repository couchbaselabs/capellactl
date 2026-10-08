"""CAP-020 AC7: next transition, including across the week boundary; CAP-019 AC7 next on-time."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from capellactl.resources.schedule import expand, next_on_text, next_text

BODY = expand({"timezone": "US/Pacific", "weekdays": "08:00-18:00", "weekend": "off", "friday": "08:00-14:30"})


@pytest.mark.story("CAP-020", "AC7")
def test_schedule_next_ac7_across_week_boundary():
    sunday_noon_pt = datetime(2026, 10, 11, 19, 0, tzinfo=timezone.utc)  # Sun 12:00 PDT
    assert next_text(BODY, sunday_noon_pt) == "on at Mon 08:00 US/Pacific"
    friday_1pm_pt = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)  # Fri 13:00 PDT
    assert next_text(BODY, friday_1pm_pt) == "off at Fri 14:30 US/Pacific"


@pytest.mark.story("CAP-019", "AC7")
def test_power_ac7_next_on_from_friday_evening():
    friday_7pm_pt = datetime(2026, 10, 10, 2, 0, tzinfo=timezone.utc)  # Fri 19:00 PDT
    assert next_on_text(BODY, friday_7pm_pt) == "Mon 08:00 US/Pacific"
