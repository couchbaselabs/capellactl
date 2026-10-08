"""CAP-028 AC2: generated passwords meet Capella's rules."""
from __future__ import annotations

import pytest

from capellactl.output.password_gen import generate_password, meets_rules


@pytest.mark.story("CAP-028", "AC2")
def test_password_gen_ac2_meets_rules():
    seen = set()
    for _ in range(10_000):
        p = generate_password()
        assert len(p) == 32 and meets_rules(p), "generated password breaks Capella's rules"
        assert not set(p) & set("<>;.*&|£")
        seen.add(p)
    assert len(seen) == 10_000


@pytest.mark.story("CAP-028", "AC3")
@pytest.mark.parametrize(("password", "ok"), [("short", False), ("alllowercase1!", False), ("ALLUPPER1!", False),
                                              ("NoDigits!!", False), ("NoSpecial12", False), ("Val1d!pw", True),
                                              ("Val1d.pw", False), ("Val1d&pw", False), ("Val1d*pw", False),
                                              ("Val1d;pw", False), ("Val1d|pw", False), ("Val1d<pw", False),
                                              ("Val1d>pw", False), ("Val1d£pw", False)])
def test_password_rules_ac3_each_rule(password, ok):
    assert meets_rules(password) is ok
