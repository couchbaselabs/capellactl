"""CAP-003 AC1: BEARER_TOKEN fallback."""
from __future__ import annotations

import pytest

from capellactl.config.settings import resolve_settings


@pytest.mark.story("CAP-003", "AC1")
def test_client_ac1_bearer_token_fallback_warns(tmp_path):
    s = resolve_settings(env={"BEARER_TOKEN": "legacy-token-123", "CAPELLACTL_HOME": str(tmp_path)})
    assert s.api_key.value == "legacy-token-123"
    assert any("BEARER_TOKEN is deprecated" in w.what for w in s.warnings)
