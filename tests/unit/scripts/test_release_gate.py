"""CAP-032 AC5: a release needs three consecutive green nightly runs, the newest on the release commit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tests.integration.harness import load_script

gate = load_script("release-gate")
ROOT = Path(__file__).resolve().parents[3]
SHA = "a" * 40


def _run(day, sha=SHA, conclusion="success", event="schedule", status="completed"):
    return {"run_started_at": f"2026-10-{day:02d}T07:03:00Z", "created_at": f"2026-10-{day:02d}T07:00:00Z",
            "head_sha": sha, "conclusion": conclusion, "event": event, "status": status,
            "html_url": f"https://github.com/o/r/actions/runs/{day}"}


@pytest.mark.story("CAP-032", "AC5")
def test_gate_ac5_three_green_nights_pass():
    ok, lines = gate.evaluate([_run(18, "b" * 40), _run(19, "c" * 40), _run(20)], SHA)
    assert ok, lines


@pytest.mark.story("CAP-032", "AC5")
@pytest.mark.parametrize("runs,reason", [
    ([_run(19), _run(20)], "only 2 completed nightly run(s)"),
    ([_run(18), _run(19, conclusion="failure"), _run(20)], "did not succeed"),
    ([_run(17), _run(19), _run(20)], "not on consecutive nights"),
    ([_run(18), _run(19), _run(20, "d" * 40)], "not the release commit"),
    # a manual run, or one still running, does not count as a night
    ([_run(18), _run(19), _run(20, event="workflow_dispatch")], "only 2"),
    ([_run(18), _run(19), _run(20, status="in_progress")], "only 2"),
    # only the last three count: an old failure does not block, a new one does
    ([_run(16, conclusion="failure"), _run(18), _run(19), _run(20, conclusion="failure")], "did not succeed"),
])
def test_gate_ac5_blocks(runs, reason):
    ok, lines = gate.evaluate(runs, SHA)
    assert not ok and reason in lines[-1], lines


@pytest.mark.story("CAP-032", "AC5")
def test_gate_ac5_cli_and_report_only(tmp_path, capsys):
    f = tmp_path / "runs.json"
    f.write_text(json.dumps({"workflow_runs": [_run(19), _run(20)]}), encoding="utf-8")
    assert gate.main(["--commit", SHA, "--runs-json", str(f)]) == 1
    assert gate.main(["--commit", SHA, "--runs-json", str(f), "--report-only"]) == 0
    assert "report only" in capsys.readouterr().out


@pytest.mark.story("CAP-032", "AC5")
def test_gate_ac5_release_workflow_runs_the_gate():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    check = wf["jobs"]["check"]
    step = next(s for s in check["steps"] if "release-gate.py" in str(s.get("run", "")))
    assert "--commit ${{ github.sha }}" in step["run"] and "--report-only" in step["run"]  # dry runs only report
    assert "github.event_name" in step["run"] and step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert check["permissions"]["actions"] == "read"
