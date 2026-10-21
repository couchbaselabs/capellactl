"""CAP-032 AC4: scripts/scan-log-secrets.py finds secrets in CI logs without printing them."""
from __future__ import annotations

import json

import pytest

from tests.integration.harness import load_script

scanner = load_script("scan-log-secrets")
KEY = "sandbox-key-0123456789abcdef"
PW = "Gen3rated!pw/+&"


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setenv("IT_KEY", KEY)
    creds = tmp_path / "it-tmp" / "test_x0" / ".capellactl" / "credentials"
    creds.mkdir(parents=True)
    (creds / "ci-01.ci_app.json").write_text(json.dumps({"name": "ci_app", "password": PW}), encoding="utf-8")
    log = tmp_path / "integration.log"
    log.write_text("DEBUG: GET /v4/organizations/o/projects 200 5ms\nAuthorization: Bearer ***\n", encoding="utf-8")
    return tmp_path, log


def _run(tmp_path, log):
    return scanner.main([str(log), "--env", "IT_KEY", "--secrets-dir", str(tmp_path / "it-tmp")])


@pytest.mark.story("CAP-032", "AC4")
def test_scan_ac4_clean_log_passes(files, capsys):
    assert _run(*files) == 0
    assert "no secrets in 1 file(s); 2 secret value(s) checked" in capsys.readouterr().out


@pytest.mark.story("CAP-032", "AC4")
@pytest.mark.parametrize("leak,label", [(KEY, "$IT_KEY"), (PW, "password in ci-01.ci_app.json"),
                                        (json.dumps(PW)[1:-1], "password in"),
                                        ("Gen3rated%21pw%2F%2B%26", "password in")])
def test_scan_ac4_leak_fails_without_printing_it(files, capsys, leak, label):
    tmp_path, log = files
    log.write_text(log.read_text(encoding="utf-8") + f"request body: {{'password': '{leak}'}}\n", encoding="utf-8")
    assert _run(tmp_path, log) == 1
    out = capsys.readouterr()
    assert f"integration.log:3: contains {label}" in out.out
    assert KEY not in out.out + out.err and PW not in out.out + out.err


@pytest.mark.story("CAP-032", "AC4")
def test_scan_ac4_missing_secret_is_an_error(files, monkeypatch):
    monkeypatch.delenv("IT_KEY")
    assert _run(*files) == 2  # an unset variable must not turn the scan into a silent pass
