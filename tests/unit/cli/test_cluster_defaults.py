"""CAP-038 AC3: defaults for new clusters."""
from __future__ import annotations

import ipaddress

import pytest

from capellactl.cli.cluster_ops import DISK_DEFAULT, PRESETS, REGION_DEFAULT, suggest_cidr


@pytest.mark.story("CAP-038", "AC3")
def test_cluster_defaults_ac3_free_cidr():
    used = ["10.10.0.0/24", "10.0.0.0/23", "10.0.2.0/24", "", "not-a-cidr"]
    got = ipaddress.ip_network(suggest_cidr(used))
    assert str(got) == "10.0.3.0/24"
    assert not any(got.overlaps(ipaddress.ip_network(u)) for u in used[:3])
    assert suggest_cidr([]) == "10.0.0.0/24"


@pytest.mark.story("CAP-038", "AC3")
def test_cluster_defaults_ac3_provider_and_presets():
    assert REGION_DEFAULT == {"aws": "us-east-1", "gcp": "us-east1", "azure": "eastus"}
    assert DISK_DEFAULT["aws"] == {"type": "gp3", "storage": 50, "iops": 3000}
    assert DISK_DEFAULT["gcp"]["type"] == "pd-ssd" and DISK_DEFAULT["azure"]["type"] == "P6"
    assert (PRESETS["small"]["nodes"], PRESETS["medium"]["cpu"], PRESETS["large"]["ram"]) == (3, 8, 64)
    assert PRESETS["dev"]["single"] is True and PRESETS["dev"]["nodes"] == 1
