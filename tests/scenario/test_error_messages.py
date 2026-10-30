"""CAP-062: every command shows config problems by name, and says whether the command caused them."""
from __future__ import annotations

import pytest

from capellactl.cli import console
from tests.conftest import MINIMAL, seed_healthy

UNKNOWN_BUCKET = "databaseCredentials:\n          - name: app\n            access:\n              - privileges: [read]\n                resources:\n                  buckets:\n                    - name: ordrs\n        "
EXISTING = "already had 1 problem before this command, so nothing was changed:"


@pytest.fixture
def imported(fake, run, tmp_path):
    _, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders")
    assert run("import").exit_code == 0
    fake.reset_calls()
    return tmp_path / "capella.yaml"


def _break(path):
    """A problem that is already in the file: a credential of nova-dev-01 names a bucket the file does not list."""
    text = path.read_text(encoding="utf-8")
    at = text.index("serviceGroups:")
    path.write_text(text[:at] + UNKNOWN_BUCKET + text[at:], encoding="utf-8")
    return path.read_text(encoding="utf-8")


@pytest.mark.story("CAP-062", "AC2")
def test_config_errors_ac2_same_in_plan(fake, run, write_config):
    write_config(MINIMAL + "    databaseCredentials:\n      - name: app\n        access:\n          - privileges: [read]\n"
                           "            resources:\n              buckets:\n                - name: ordrs\n")
    r = run("plan")
    assert r.exit_code == 3, r.output
    assert r.output.startswith("[ERROR]: capella.yaml has 1 problem:\n"
                               "  project nova-dev › cluster nova-dev-01 › credential app › "
                               "access[0].resources.buckets[0].name (line 24)\n"
                               "    the credential gives access to bucket 'ordrs'"), r.output
    assert "    action: 'capellactl sync --project nova-dev'" in r.output
    assert "\n[ACTION]: Fix each problem above (an 'action:' line says how), then run the command again." in r.output and fake.calls() == []


@pytest.mark.story("CAP-062", "AC3")
def test_config_errors_ac3_existing_problems(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    before = _break(imported)
    r = run("cluster", "create", "test-01", input="\n" * 20)
    assert r.exit_code == 3 and r.output.startswith(f"[ERROR]: capella.yaml {EXISTING}\n"), r.output
    assert "cluster nova-dev-01 › credential app" in r.output
    assert "Cloud provider" not in r.output and "Cluster type" not in r.output
    assert imported.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-062", "AC3")
def test_config_errors_ac3_caused_by_change(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "bad-01", "--cidr", "10.10.0.0/24")
    assert r.exit_code == 3, r.output
    assert r.output.startswith("[ERROR]: This change is not valid, so nothing was changed:\n"
                               "  project nova-dev › cluster bad-01 › cloudProvider.cidr"), r.output
    assert "overlaps the network of cluster 'nova-dev-01'" in r.output and "Already in" not in r.output


@pytest.mark.story("CAP-062", "AC3")
def test_config_errors_ac3_both(fake, run, imported):
    # Schema problems are reported before cross-reference ones, so both problems here are schema problems.
    imported.write_text(imported.read_text(encoding="utf-8").replace("plan: developer pro", "plan: gold"), encoding="utf-8")
    before = imported.read_text(encoding="utf-8")
    r = run("--auto-approve", "bucket", "backup", "schedule", "set", "nova-dev-01", "orders", "--incremental-every", "3")
    assert r.exit_code == 3, r.output
    own = r.output.index("This change is not valid, so nothing was changed:\n"
                         "  project nova-dev › cluster nova-dev-01 › bucket orders › backupSchedule.incrementalEvery")
    old = r.output.index("Already in capella.yaml before this command:\n"
                         "  project nova-dev › cluster nova-dev-01 › support.plan")
    assert own < old
    assert imported.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-062", "AC5")
def test_config_errors_ac5_reask_provider_and_size(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    # azure + dev (a single node, AWS only) is refused, then provider and size are asked again: aws + small deploys
    r = run("cluster", "create", "nova-dev-03", "--availability", "multi",
            input="\nazure\ndev\n\n\n\naws\nsmall\n\n\n\ny\n")
    assert "[ACTION]: Please try again" in r.output and r.output.count("Cloud provider") == 2, r.output
    assert "[ERROR]: This change is not valid, so nothing was changed:\n  project nova-dev › cluster nova-dev-03" in r.output
    assert r.exit_code == 0, r.output
