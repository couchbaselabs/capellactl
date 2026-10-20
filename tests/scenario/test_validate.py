"""CAP-002 AC1, AC6: validate command."""
from __future__ import annotations

import shutil
import socket

import pytest

from tests.conftest import EXAMPLE, MINIMAL


@pytest.mark.story("CAP-002", "AC1")
def test_validate_ac1_exit_code_3(run, write_config):
    write_config(MINIMAL.replace("numOfNodes: 3", "numOfNodes: 2"))
    r = run("validate")
    assert r.exit_code == 3
    assert "clusters[0].serviceGroups[0].numOfNodes: must be between 3 and 27 (line 16)" in r.output
    assert "See: capellactl help scaling" in r.output


@pytest.mark.story("CAP-002", "AC6")
def test_validate_ac6_example_is_valid_offline(run, tmp_path, monkeypatch):
    shutil.copy(EXAMPLE, tmp_path / "capella.yaml")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "reporting_ro.txt").write_text("R3port!ng-pw\n", encoding="utf-8")

    def no_network(*a, **k):
        raise AssertionError("validate must not use the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    r = run("validate", extra_env={"ORDERS_APP_PASSWORD": "Orders#App-123"})
    assert r.exit_code == 0, r.output
    assert ("Configuration valid: 1 project, 1 cluster, 2 buckets, 3 scopes, 4 collections, 3 credentials, "
            "2 allowed CIDRs, 1 hibernation schedule") in r.output
