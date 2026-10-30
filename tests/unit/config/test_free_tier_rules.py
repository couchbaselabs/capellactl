"""CAP-041 AC4: free-tier validation."""
from __future__ import annotations

import pytest

from capellactl.config.loader import ConfigError, load_config

BASE = """\
apiVersion: capellactl/v1
organizationId: org-1
projects:
  - name: demo
    clusters:
      - name: try-01
        tier: free
        cloudProvider: {type: aws, region: us-east-2, cidr: 10.0.0.0/23}
"""


def _check(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(text, encoding="utf-8")
    return load_config(p, env={})


@pytest.mark.story("CAP-041", "AC4")
def test_free_tier_ac4_validation(tmp_path):
    cfg = _check(tmp_path, BASE)
    assert "configurationType" not in cfg.clusters[0]
    with pytest.raises(ConfigError, match="free-tier clusters on aws are available in: us-east-2, eu-west-1"):
        _check(tmp_path, BASE.replace("us-east-2", "us-west-2"))
    with pytest.raises(ConfigError, match=r"availability \(line \d+\)\n    not available for free-tier clusters"):
        _check(tmp_path, BASE + "        availability: {type: single}\n")
    with pytest.raises(ConfigError, match=r"support \(line \d+\)\n    not available for free-tier clusters"):
        _check(tmp_path, BASE + "        support: {plan: basic}\n")
    two = BASE + BASE.split("    clusters:\n", 1)[1].replace("try-01", "try-02").replace("10.0.0.0", "10.2.0.0")
    with pytest.raises(ConfigError, match="only one free-tier cluster is allowed per organization"):
        _check(tmp_path, two)
    with pytest.raises(ConfigError, match="missing required field 'serviceGroups'"):
        _check(tmp_path, BASE.replace("        tier: free\n", ""))
