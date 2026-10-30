"""CAP-060 AC3: without --disk-iops, a disk gets Capella's recommended IOPS for its size."""
from __future__ import annotations

import pytest

from capellactl.cli.cluster_ops import make_disk


@pytest.mark.story("CAP-060", "AC3")
@pytest.mark.parametrize("provider,disk_type,size,iops", [
    ("aws", "gp3", 50, 3000), ("aws", "gp3", 99, 3000), ("aws", "gp3", 100, 4370), ("aws", "io2", 200, 5740),
    ("aws", "gp3", 500, 9850), ("aws", "gp3", 999, 15330), ("aws", "io2", 1000, 16000), ("aws", "gp3", 4000, 16000),
    ("azure", "Ultra", 64, 3000), ("azure", "Ultra", 256, 6000), ("azure", "Ultra", 2048, 16000),
])
def test_disk_types_ac3_iops_default(provider, disk_type, size, iops):
    assert make_disk(provider, disk_type, size) == {"type": disk_type, "storage": size, "iops": iops}


@pytest.mark.story("CAP-060", "AC3")
def test_disk_types_ac3_defaults_per_provider():
    assert make_disk("aws") == {"type": "gp3", "storage": 50, "iops": 3000}
    assert make_disk("aws", size=300) == {"type": "gp3", "storage": 300, "iops": 7110}
    assert make_disk("aws", "io2", 300, 20000) == {"type": "io2", "storage": 300, "iops": 20000}  # given wins
    assert make_disk("gcp", size=100) == {"type": "pd-ssd", "storage": 100}  # IOPS follow size: none sent
    assert make_disk("azure", "P15") == {"type": "P15"}  # set by the type
    assert make_disk("azure", "Ultra") == {"type": "Ultra", "storage": 64, "iops": 3000}  # the smallest Ultra size
