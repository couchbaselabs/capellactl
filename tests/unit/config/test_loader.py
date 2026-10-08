"""CAP-002 AC1, AC7: schema errors and apiVersion."""
from __future__ import annotations

import pytest

from capellactl.config.loader import ConfigError, load_config
from tests.conftest import MINIMAL

ENV = {"CAPELLA_ORG_ID": "org-1"}

INVALID = [
    ("numOfNodes: 3", "numOfNodes: 2", "clusters[0].serviceGroups[0].numOfNodes: must be between 3 and 27 (line 16)"),
    ("type: aws", "type: ibm", "clusters[0].cloudProvider.type: must be one of: aws, gcp, azure (line 9)"),
    ("plan: developer pro", "plan: gold", "clusters[0].support.plan: must be one of:"),
    ("    description: Nova development cluster\n", "    descripton: x\n", "unknown field 'descripton' (did you mean 'description'?)"),
    ("  name: nova-dev\n", "", "project: missing required field 'name'"),
    ("cpu: 4", "cpu: four", "clusters[0].serviceGroups[0].node.compute.cpu: must be an integer"),
    ("services: [data, index, query]", "services: [data, cache]", "must be one of: data, index, query, search, analytics, eventing"),
    ("type: gp3", "type: P20", "disk type P20 is not valid for aws"),
    ("services: [data, index, query]", "services: [index, query]", "at least one service group must run the data service"),
    ("availability: { type: multi }", "availability: { type: everywhere }", "clusters[0].availability.type: must be one of: single, multi"),
]


@pytest.mark.story("CAP-002", "AC1")
@pytest.mark.parametrize("old,new,expected", INVALID)
def test_loader_ac1_error_has_path_and_line(tmp_path, old, new, expected):
    assert old in MINIMAL
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL.replace(old, new, 1))
    with pytest.raises(ConfigError) as ei:
        load_config(p, env=ENV)
    text = str(ei.value)
    assert expected in text
    assert "(line " in text


@pytest.mark.story("CAP-002", "AC7")
def test_loader_ac7_unknown_api_version(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL.replace("capellactl/v1", "capellactl/v2"))
    with pytest.raises(ConfigError) as ei:
        load_config(p, env=ENV)
    assert "this file needs capellactl supporting capellactl/v2; installed version supports capellactl/v1" in str(ei.value)
