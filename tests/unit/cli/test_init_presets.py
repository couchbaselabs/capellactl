"""CAP-035 AC3: size presets come from presets.yaml; dev is a single AWS node."""
from __future__ import annotations

import pytest

from capellactl.cli import init as init_mod
from capellactl.cli.init import Answers, build_document, issues
from capellactl.cli.state import AppState
from capellactl.config import presets


def _answers(**kw):
    return Answers(org_id="org-1", project="nova-dev", cluster="nova-dev-01", **kw)


@pytest.mark.story("CAP-035", "AC3")
def test_init_ac3_presets_from_file(monkeypatch):
    cl = build_document(_answers(preset="dev"))["clusters"][0]
    assert cl["configurationType"] == "singleNode"
    assert cl["availability"] == {"type": "single"}
    assert cl["serviceGroups"][0]["numOfNodes"] == 1
    cl = build_document(_answers(preset="small"))["clusters"][0]
    assert "configurationType" not in cl  # multiNode is the default
    assert cl["availability"] == {"type": "multi"}
    assert cl["serviceGroups"][0]["numOfNodes"] == 3
    assert cl["serviceGroups"][0]["services"] == ["data", "index", "query"]
    assert issues(AppState(env={}), _answers(preset="small")) == []
    # the values are read from presets.yaml, not from code
    custom = {"small": {"configurationType": "multiNode", "availability": "multi", "numOfNodes": 5, "cpu": 8,
                        "ram": 32, "services": ["data", "query", "index"]}}
    monkeypatch.setattr(init_mod, "load_presets", lambda: custom)
    g = build_document(_answers(preset="small"))["clusters"][0]["serviceGroups"][0]
    assert (g["numOfNodes"], g["node"]["compute"]) == (5, {"cpu": 8, "ram": 32})


@pytest.mark.story("CAP-035", "AC3")
def test_init_ac3_presets_file_shipped():
    p = presets.load_presets()
    assert {"dev", "small"} <= set(p)
    assert presets.is_single_node(p["dev"]) and not presets.is_single_node(p["small"])


@pytest.mark.story("CAP-035", "AC3")
@pytest.mark.parametrize("provider", ["gcp", "azure"])
def test_init_ac3_dev_preset_any_provider(provider):
    found = issues(AppState(env={}), _answers(preset="dev", provider=provider, region="r1"))
    assert not any(i.path == "clusters[0].cloudProvider.type" for i in found)
    assert issues(AppState(env={}), _answers(preset="dev")) == []
