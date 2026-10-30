"""CAP-008 AC1, AC5: no secret in any output channel."""
from __future__ import annotations

import logging

import pytest

from tests.conftest import API_KEY, MINIMAL, assert_no_secret, seed_healthy

PW = "Canary!Passw0rd-xyz"
CRED = """\
    buckets:
      - name: orders
        memoryAllocationInMb: 1024
    databaseCredentials:
      - name: app
        password: ${APP_PW}
        access:
          - privileges: [read]
            resources: { buckets: [ { name: orders } ] }
"""


@pytest.mark.story("CAP-008", "AC1")
def test_redaction_ac1_canary_never_printed(fake, run, write_config, caplog):
    seed_healthy(fake)
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 4") + CRED)
    env = {"APP_PW": PW}
    outputs = []
    with caplog.at_level(logging.DEBUG, logger="capellactl"):
        for args in (["validate"], ["--log-level", "debug", "plan"], ["-o", "json", "plan"],
                     ["--log-level", "debug", "--auto-approve", "apply"]):
            outputs.append(run(*args, extra_env=env).output)
        fake.fail_next("GET", "*/projects", 500, times=6)
        outputs.append(run("--log-level", "debug", "plan", extra_env=env).output)
    joined = "\n".join(outputs) + caplog.text
    assert "request body" in joined or "GET /v4/" in joined  # debug logging really happened
    assert_no_secret(joined, API_KEY, PW)


@pytest.mark.story("CAP-008", "AC5")
def test_redaction_ac5_uncaught_exception_redacted(fake, run, write_config, monkeypatch):
    write_config()

    def boom(*a, **k):
        raise RuntimeError(f"unexpected failure while using key {API_KEY}")

    monkeypatch.setattr("capellactl.cli.env.build_plan", boom)
    r = run("plan")
    assert r.exit_code == 1
    assert "[ERROR]: unexpected error: unexpected failure while using key ***\n[ACTION]: " in r.output
    r = run("--log-level", "debug", "plan")
    assert "Traceback" in r.output
    assert_no_secret(r.output, API_KEY)
