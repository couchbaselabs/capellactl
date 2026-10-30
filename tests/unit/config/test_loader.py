"""CAP-002 AC1, AC7: schema errors and apiVersion."""
from __future__ import annotations

import pytest

from capellactl.config.loader import ConfigError, load_config
from tests.conftest import MINIMAL

ENV = {"CAPELLA_ORG_ID": "org-1"}

INVALID = [
    ("numOfNodes: 3", "numOfNodes: 2", "service group data,index,query › numOfNodes (line 16)\n    must be between 3 and 27"),
    ("type: aws", "type: ibm", "cluster nova-dev-01 › cloudProvider.type (line 9)\n    must be one of: aws, gcp, azure"),
    ("plan: developer pro", "plan: gold", "cluster nova-dev-01 › support.plan (line 11)\n    must be one of:"),
    ("    description: Nova development cluster\n", "    descripton: x\n", "unknown field 'descripton' (did you mean 'description'?)"),
    ("  name: nova-dev\n", "", "project (line 3)\n    missing required field 'name'"),
    ("cpu: 4", "cpu: four", "service group data,index,query › node.compute.cpu (line 14)\n    must be an integer"),
    ("services: [data, index, query]", "services: [data, cache]", "must be one of: data, index, query, search, analytics, eventing"),
    ("type: gp3", "type: P20", "disk type P20 is not valid for aws"),
    ("services: [data, index, query]", "services: [index, query]", "at least one service group must run the data service"),
    ("availability: { type: multi }", "availability: { type: everywhere }", "cluster nova-dev-01 › availability.type (line 10)\n    must be one of: single, multi"),
]


@pytest.mark.story("CAP-002", "AC1")
@pytest.mark.parametrize("old,new,expected", INVALID)
def test_loader_ac1_error_has_path_and_line(tmp_path, old, new, expected):
    assert old in MINIMAL
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(p, env=ENV)
    text = str(ei.value)
    assert expected in text
    assert "(line " in text


@pytest.mark.story("CAP-002", "AC7")
def test_loader_ac7_unknown_api_version(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL.replace("capellactl/v1", "capellactl/v2"), encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(p, env=ENV)
    assert "this file needs capellactl supporting capellactl/v2; installed version supports capellactl/v1" in str(ei.value)
