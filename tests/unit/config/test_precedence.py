"""CAP-037 AC3: precedence of settings."""
from __future__ import annotations

import pytest

from capellactl.config.settings import keychain_set, resolve_settings, save_profiles


@pytest.mark.story("CAP-037", "AC3")
@pytest.mark.parametrize("env_org,profile_flag,file_org,expected,source", [
    (None, None, None, "org-A", "profile default"),
    ("org-B", None, None, "org-B", "CAPELLA_ORG_ID"),
    (None, "prod", None, "org-P", "profile prod"),
    ("org-B", "prod", None, "org-B", "CAPELLA_ORG_ID"),
    (None, "missing", "org-F", "org-F", "config file"),
])
def test_configure_ac3_precedence_matrix(tmp_path, env_org, profile_flag, file_org, expected, source):
    env = {"CAPELLACTL_HOME": str(tmp_path)}
    save_profiles({"default": {"organizationId": "org-A"}, "prod": {"organizationId": "org-P"}}, env)
    keychain_set("default", "key-default-1234")
    keychain_set("prod", "key-prod-5678")
    if env_org:
        env["CAPELLA_ORG_ID"] = env_org
    s = resolve_settings(profile_flag=profile_flag, env=env, file_org_id=file_org)
    assert (s.org_id.value, s.org_id.source) == (expected, source)
    if profile_flag == "prod":
        assert s.api_key.value == "key-prod-5678"
    env["CAPELLA_API_KEY"] = "key-env-0000"
    assert resolve_settings(profile_flag=profile_flag, env=env).api_key.value == "key-env-0000"
