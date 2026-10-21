"""CAP-032: the integration suite's teardown guarantee and its CI wiring, checked on every push against the fake."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from capellactl.api.errors import Conflict
from tests.conftest import API_KEY, ORG
from tests.integration.harness import Target, single_node

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def target(fake, tmp_path):
    return Target("fake", API_KEY, ORG, tmp_path / "integration.log", fake=fake, run="t1",
                  timeout=timedelta(minutes=5))


def _deploy(target, tmp_path, project):
    cfg = tmp_path / "capella.yaml"
    cfg.write_text(single_node(project, "ci-01", "10.40.0.0/24", "    deletionProtection: true\n"), encoding="utf-8")
    r = target.cli("apply", cfg=cfg)
    assert r.exit_code == 0, r.output


@pytest.mark.story("CAP-032", "AC3")
def test_integration_ac3_teardown_on_failure(fake, target, tmp_path):
    project = target.project_name("t")
    with pytest.raises(RuntimeError, match="injected"), target.cleanup(project):
        _deploy(target, tmp_path, project)
        raise RuntimeError("injected failure")
    assert fake.projects == {} and all(c["deleted_at"] is not None for c in fake.clusters.values())
    (entry,) = target.report
    assert entry["failure"] == "RuntimeError: injected failure"
    assert entry["teardown"].startswith("ok: deletion protection off for ci-01; deleted cluster ci-01")
    assert any("FAILED: RuntimeError: injected failure" in line for line in target.summary())


@pytest.mark.story("CAP-032", "AC3")
def test_integration_ac3_failed_teardown_fails_a_passing_test(fake, target, tmp_path):
    project = target.project_name("t")
    fake.fail_next("DELETE", "*/projects/*", 409, times=100)
    with pytest.raises(Conflict), target.cleanup(project):  # the API error of the last attempt
        _deploy(target, tmp_path, project)
    (entry,) = target.report
    assert entry["failure"] is None and entry["teardown"].startswith("FAILED:")


@pytest.mark.story("CAP-032", "AC3")
def test_integration_ac3_both_failures_reported(fake, target, tmp_path):
    project = target.project_name("t")
    fake.fail_next("DELETE", "*/projects/*", 409, times=100)
    with pytest.raises(RuntimeError, match="injected"), target.cleanup(project):  # the test's own failure wins
        _deploy(target, tmp_path, project)
        raise RuntimeError("injected failure")
    (entry,) = target.report
    assert entry["failure"] == "RuntimeError: injected failure" and entry["teardown"].startswith("FAILED:")


@pytest.mark.story("CAP-032", "AC1")
def test_integration_ac1_zero_writes_read_from_the_request_log(fake, target, tmp_path):
    project = target.project_name("t")
    with target.cleanup(project):
        _deploy(target, tmp_path, project)
        r = target.cli("apply", cfg=tmp_path / "capella.yaml")
        assert r.requests and r.writes == []
        r = target.cli("cluster", "protect", "ci-01", "--off", cfg=tmp_path / "capella.yaml")
        assert [m for m, _, _ in r.writes] == ["PUT"]
    log = target.log_path.read_text(encoding="utf-8")
    assert log.count("$ capellactl --log-level debug") == 3 and "[exit 0]" in log


def _workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


@pytest.mark.story("CAP-032", "AC1")
def test_integration_nightly_workflow():
    wf = _workflow("nightly.yml")
    on = wf[True]  # YAML reads the key `on` as a boolean
    crons = [s["cron"] for s in on["schedule"]]
    assert len(crons) == 2 and "workflow_dispatch" in on
    job = wf["jobs"]["integration"]
    assert job["env"]["CAPELLA_SANDBOX_API_KEY"] == "${{ secrets.CAPELLA_SANDBOX_API_KEY }}"
    assert job["env"]["CAPELLACTL_IT_TARGET"] == "sandbox"
    runs = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert "-m integration" in runs and "--basetemp" in runs
    scan = next(s for s in job["steps"] if "scan-log-secrets.py" in str(s.get("run", "")))
    assert scan["if"] == "always()" and "--env CAPELLA_SANDBOX_API_KEY" in scan["run"]
    upload = next(s for s in job["steps"] if "upload-artifact" in str(s.get("uses", "")))
    assert upload["if"] == "always()" and "it-tmp" not in str(upload["with"]["path"])  # never the saved passwords
    janitor = wf["jobs"]["janitor"]
    assert "ci-janitor.py" in "\n".join(str(s.get("run", "")) for s in janitor["steps"])


@pytest.mark.story("CAP-032", "AC1")
def test_integration_rehearsed_on_every_push():
    """The suite runs against the fake in CI and `make check`, so a broken integration test is caught before night."""
    steps = _workflow("ci.yml")["jobs"]["test"]["steps"]
    rehearsal = next(s for s in steps if "-m integration" in str(s.get("run", "")))
    assert rehearsal["env"]["CAPELLACTL_IT_TARGET"] == "fake"
    make = (ROOT / "Makefile").read_text(encoding="utf-8")
    check = next(line for line in make.splitlines() if line.startswith("check:"))
    assert "CAPELLACTL_IT_TARGET=fake" in make and "test-integration-fake" in check.split()
