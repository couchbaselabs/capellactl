"""CAP-037 AC7: pasted keys are cleaned."""
from __future__ import annotations

import pytest

from capellactl.cli.configure import clean_api_key

KEY = "AbC123xyz.0987654321-key"


@pytest.mark.story("CAP-037", "AC7")
@pytest.mark.parametrize("raw,fixes", [
    (KEY, []),
    (f"  {KEY}\n", []),
    (f'"{KEY}"', ["removed surrounding quotes"]),
    (f"Bearer {KEY}", ["removed a leading 'Bearer '"]),
    (f"{KEY[:10]}\n{KEY[10:]}", ["removed 1 line break/space/control character(s)"]),
    (f"\x1b[200~{KEY}\x1b[201~", ["removed terminal paste markers"]),
])
def test_configure_ac7_cleans_pasted_key(raw, fixes):
    key, fixed = clean_api_key(raw)
    assert key == KEY
    assert fixed == fixes
    assert all(KEY not in f for f in fixed)
