"""CAP-032 AC1: a whole environment against the sandbox: apply → apply (zero writes) → edit → apply → destroy."""
from __future__ import annotations

import pytest

from tests.integration.harness import single_node

pytestmark = pytest.mark.integration

# Always on (00:00-24:00, weekend on), so the schedule never turns the cluster off while the suite runs.
ENVIRONMENT = """\
    deletionProtection: true
    hibernation:
      timezone: US/Pacific
      weekdays: "00:00-24:00"
      weekend: "on"
    allowedCidrs:
      - cidr: 203.0.113.10/32
        comment: capellactl nightly
    buckets:
      - name: orders
        memoryAllocationInMb: 256
        scopes:
          - name: inventory
            collections:
              - name: items
    databaseCredentials:
      - name: ci_app
        access:
          - privileges: [data_reader]
            resources:
              buckets:
                - name: orders
credentialsOutput: ./.capellactl/credentials
"""
EDITS = [("memoryAllocationInMb: 256", "memoryAllocationInMb: 512"),
         ("comment: capellactl nightly", "comment: capellactl nightly, edited"),
         ("timezone: US/Pacific", "timezone: US/Eastern")]


@pytest.mark.story("CAP-032", "AC1")
def test_integration_ac1_lifecycle(it, tmp_path):
    project, cfg = it.project_name("life"), tmp_path / "capella.yaml"
    cfg.write_text(single_node(project, "ci-life-01", "10.40.0.0/24", ENVIRONMENT), encoding="utf-8")
    with it.cleanup(project):
        r = it.cli("apply", cfg=cfg)
        assert r.exit_code == 0, r.output
        assert r.writes, "the first apply created nothing"

        r = it.cli("apply", cfg=cfg)
        assert r.exit_code == 0 and "No changes" in r.output, r.output
        assert r.writes == [], f"a re-run wrote to Capella: {r.writes}"

        text = cfg.read_text(encoding="utf-8")
        for old, new in EDITS:
            assert old in text, old
            text = text.replace(old, new, 1)
        cfg.write_text(text, encoding="utf-8")
        r = it.cli("apply", cfg=cfg)
        assert r.exit_code == 0, r.output
        paths = [p for _, p, _ in r.writes]
        for part in ("/buckets/", "/onOffSchedule", "/allowedcidrs"):  # the three edits
            assert any(part in p for p in paths), (part, r.writes)

        r = it.cli("apply", cfg=cfg)
        assert r.exit_code == 0 and r.writes == [], r.output  # the edits converged

        r = it.cli("cluster", "protect", "ci-life-01", "--off", cfg=cfg)
        assert r.exit_code == 0, r.output
        r = it.cli("destroy", "--discard-snapshots", cfg=cfg)
        assert r.exit_code == 0, r.output
        r = it.cli("project", "list", approve=False)
        assert project not in r.output, r.output
