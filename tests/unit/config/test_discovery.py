"""CAP-037 AC5: config file discovery."""
from __future__ import annotations

import pytest

from capellactl.config.settings import ConfigDiscoveryError, discover_config_file


@pytest.mark.story("CAP-037", "AC5")
def test_discovery_ac5_yml_used(tmp_path):
    (tmp_path / "capella.yml").write_text("x")
    assert discover_config_file(None, {}, {}, tmp_path).value == "capella.yml"


@pytest.mark.story("CAP-037", "AC5")
def test_discovery_ac5_both_present_error(tmp_path):
    (tmp_path / "capella.yml").write_text("x")
    (tmp_path / "capella.yaml").write_text("x")
    with pytest.raises(ConfigDiscoveryError, match="both capella.yaml and capella.yml found; pass --config"):
        discover_config_file(None, {}, {}, tmp_path)


@pytest.mark.story("CAP-037", "AC5")
def test_discovery_ac5_profile_config_file(tmp_path):
    assert discover_config_file(None, {}, {"configFile": "envs/prod.yaml"}, tmp_path).value == "envs/prod.yaml"
    assert discover_config_file(None, {"CAPELLACTL_CONFIG": "e.yaml"}, {"configFile": "p.yaml"}, tmp_path).value == "e.yaml"
    assert discover_config_file("f.yaml", {"CAPELLACTL_CONFIG": "e.yaml"}, {}, tmp_path).value == "f.yaml"


@pytest.mark.story("CAP-037", "AC5")
def test_discovery_ac5_both_present_cli_exit_3(run, tmp_path):
    (tmp_path / "capella.yml").write_text("x")
    (tmp_path / "capella.yaml").write_text("x")
    r = run("validate")
    assert r.exit_code == 3 and "both capella.yaml and capella.yml found" in r.output
