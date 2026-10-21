"""CAP-032 AC4: the run's captured log holds no secret: the API key, the passwords tests set, and every password
Capella generated (saved under the tests' credentialsOutput). The nightly job scans the complete log again after the
run (scripts/scan-log-secrets.py); this test fails the suite itself as soon as a leak is in the log."""
from __future__ import annotations

import pytest

from tests.integration.harness import load_script
from tests.integration.test_credentials import PASSWORD

pytestmark = pytest.mark.integration
scanner = load_script("scan-log-secrets")


@pytest.mark.story("CAP-032", "AC4")
def test_integration_ac4_logs_have_no_secrets(it, shared, tmp_path_factory):
    secrets = {"API key": it.api_key, "test password": PASSWORD,
               **scanner.secrets_in_dir(tmp_path_factory.getbasetemp())}
    log = it.log_path.read_text(encoding="utf-8")
    assert "DEBUG: GET /v4/" in log  # the log really holds debug output
    assert scanner.scan({"integration log": log}, secrets) == []
