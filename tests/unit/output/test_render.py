"""CAP-005 AC1: one symbol per action type."""
from __future__ import annotations

import pytest

from capellactl.output.render import render_plan_text
from capellactl.resources.base import Action, ActionType, Change, Plan
from capellactl.resources.unsupported import placeholders


@pytest.mark.story("CAP-005", "AC1")
def test_render_ac1_each_action_type_symbol():
    rec = placeholders()[0]
    acts = [Action("bucket", f"c/{t.value}", t, rec, reason="why", summary="s") for t in ActionType]
    acts[2].changes = [Change("memoryAllocationInMb", 1024, 2048)]
    text = render_plan_text(Plan(acts))
    for t, sym in [("noop", "="), ("create", "+"), ("update", "~"), ("replace", "±"), ("delete", "-"),
                   ("blocked", "!"), ("deferred", "…")]:
        assert f"  {sym} bucket c/{t}" in text
    assert "      memoryAllocationInMb:  1024 → 2048" in text
    assert text.endswith("Plan: 2 to add, 1 to change, 1 to delete, 1 blocked, 1 deferred.")
