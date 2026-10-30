"""CAP-062: config problems name where they are, are counted, and give a command as the fix."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from capellactl.config.loader import ConfigError, load_config
from tests.conftest import MINIMAL

ENV = {"CAPELLA_ORG_ID": "o"}
HOST_BITS = "    allowedCidrs:\n      - cidr: 10.0.0.5/24\n"
CREDENTIAL = """\
    databaseCredentials:
      - name: app
        access:
          - privileges: [read]
            resources:
              buckets:
                - name: ordrs
"""
INDEX_PATH = re.compile(r"\b(projects|clusters|serviceGroups|databaseCredentials|allowedCidrs)\[\d+\]")


def _error(tmp_path, text) -> str:
    p = tmp_path / "capella.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(p, env=ENV)
    return str(ei.value)


@pytest.mark.story("CAP-062", "AC1")
@pytest.mark.parametrize("text,where", [
    (MINIMAL + HOST_BITS, r"project nova-dev › cluster nova-dev-01 › allowed IP range 10\.0\.0\.5/24 \(line 19\)"),
    (MINIMAL.replace("numOfNodes: 3", "numOfNodes: 2"),
     r"project nova-dev › cluster nova-dev-01 › service group data,index,query › numOfNodes \(line 16\)"),
    (MINIMAL + CREDENTIAL,
     r"project nova-dev › cluster nova-dev-01 › credential app › access\[0\]\.resources\.buckets\[0\]\.name \(line 24\)"),
])
def test_config_errors_ac1_named_location(tmp_path, text, where):
    msg = _error(tmp_path, text)
    assert re.search(where, msg), msg
    assert not INDEX_PATH.search(msg), msg


@pytest.mark.story("CAP-062", "AC1")
def test_config_errors_ac1_unnamed_and_root(tmp_path):
    second = MINIMAL.split("clusters:\n", 1)[1].replace("  - name: nova-dev-01\n", "  - description: no name\n")
    assert "cluster #2 (line 18)\n    missing required field 'name'" in _error(tmp_path, MINIMAL + second)
    assert "apiVersion (line 1)\n    must be capellactl/v1" in _error(tmp_path, MINIMAL.replace("capellactl/v1", "v0"))


@pytest.mark.story("CAP-062", "AC2")
def test_config_errors_ac2_heading_and_blocks(tmp_path):
    second = MINIMAL.split("clusters:\n", 1)[1].replace("nova-dev-01", "nova-dev-02").replace("10.10.", "10.20.")
    msg = _error(tmp_path, MINIMAL + CREDENTIAL + second + CREDENTIAL)
    lines = msg.splitlines()
    assert lines[0] == "capella.yaml has 2 problems:"
    assert lines[1] == ("  project nova-dev › cluster nova-dev-01 › credential app › "
                        "access[0].resources.buckets[0].name (line 24)")
    assert lines[2] == ("    the credential gives access to bucket 'ordrs', which capella.yaml does not list for "
                        "cluster 'nova-dev-01'")
    assert lines[3].startswith("    action: 'capellactl sync --project nova-dev'")
    assert lines[4].startswith("  project nova-dev › cluster nova-dev-02 › credential app › ")


@pytest.mark.story("CAP-062", "AC4")
def test_config_errors_ac4_fix_commands(tmp_path):
    msg = _error(tmp_path, MINIMAL + CREDENTIAL)
    assert "action: 'capellactl sync --project nova-dev' adds the bucket if it exists in Capella, or " \
           "'capellactl bucket create nova-dev-01 ordrs --project nova-dev' creates it" in msg


# "add password: …", "set allowAnyIp: true", "add id: …": telling the reader to write a field into the file.
HAND_EDIT = re.compile(r"""["'][^"'\n]*\b(?:[Aa]dd|[Ss]et)\s+[A-Za-z]+:(?:\s|$|["'])""")


@pytest.mark.story("CAP-062", "AC4")
def test_config_errors_ac4_no_hand_edit_advice():
    root = Path(__file__).resolve().parents[3] / "capellactl"
    found = [f"{p.relative_to(root)}:{n}: {line.strip()}" for p in sorted(root.rglob("*.py"))
             for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if HAND_EDIT.search(line)]
    assert found == []
