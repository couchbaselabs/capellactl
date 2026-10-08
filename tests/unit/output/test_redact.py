"""CAP-008 AC1: redaction primitives."""
from __future__ import annotations

import pytest

from capellactl.output.redact import MASK, Redactor


@pytest.mark.story("CAP-008", "AC1")
def test_redact_ac1_masks_registered_values():
    r = Redactor()
    r.register("abc12345")
    r.register("abc12345-longer")
    assert r.redact("key abc12345-longer and abc12345") == f"key {MASK} and {MASK}"
    r.register("ab")  # too short to register safely
    assert r.redact("ab") == "ab"


@pytest.mark.story("CAP-008", "AC1")
def test_redact_ac1_masks_password_keys_in_objects():
    r = Redactor()
    obj = {"name": "u", "password": "p1-secret", "nested": [{"Password": "p2"}, {"Authorization": "Bearer x"}],
           "empty": {"password": ""}}
    assert r.redact_obj(obj) == {"name": "u", "password": MASK, "nested": [{"Password": MASK}, {"Authorization": MASK}],
                                 "empty": {"password": ""}}
