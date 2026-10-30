"""CAP-060 AC4: disk sizes and IOPS outside what the type accepts are refused offline."""
from __future__ import annotations

import pytest

from capellactl.config.crossref import config_warnings
from capellactl.config.loader import ConfigError, load_config
from tests.conftest import MINIMAL

ENV = {"CAPELLA_ORG_ID": "o"}
AWS_DISK = "disk: { type: gp3, storage: 50, iops: 3000 }"


def _text(disk: str, provider: str = "aws") -> str:
    region = {"aws": "us-east-1", "gcp": "us-east1", "azure": "eastus"}[provider]
    return MINIMAL.replace(AWS_DISK, disk).replace("type: aws, region: us-east-1", f"type: {provider}, region: {region}")


def _load(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(text, encoding="utf-8")
    return load_config(p, env=ENV)


@pytest.mark.story("CAP-060", "AC4")
@pytest.mark.parametrize("provider,disk,message", [
    ("aws", "disk: { type: gp3, storage: 50, iops: 20000 }", "gp3 disks take 3000–16000 IOPS (got 20000)"),
    ("aws", "disk: { type: io2, storage: 50, iops: 2000 }", "io2 disks take 3000–64000 IOPS (got 2000)"),
    ("aws", "disk: { type: gp3, storage: 20000, iops: 16000 }", "gp3 disks are at most 16000 GB (got 20000)"),
    ("azure", "disk: { type: Ultra, storage: 100, iops: 3000 }", "Ultra disks come in 64, 128, 256, 512, 1024, … 15360"),
    ("azure", "disk: { type: Ultra, storage: 64, iops: 20000 }", "Ultra disks take 3000–19200 IOPS at 64 GB"),
])
def test_disk_types_ac4_refused(tmp_path, provider, disk, message):
    with pytest.raises(ConfigError) as ei:
        _load(tmp_path, _text(disk, provider))
    assert message in str(ei.value) and "capellactl cluster disk-types" in str(ei.value)


@pytest.mark.story("CAP-060", "AC4")
@pytest.mark.parametrize("provider,disk", [
    ("aws", "disk: { type: io2, storage: 300, iops: 64000 }"),
    ("aws", "disk: { type: gp3, storage: 150, iops: 3000 }"),  # Capella allows 3000 for 100–199 GB
    ("gcp", "disk: { type: pd-ssd, storage: 30000 }"),  # no documented maximum
    ("azure", "disk: { type: Ultra, storage: 512, iops: 80000 }"),
    ("azure", "disk: { type: P30 }"),
])
def test_disk_types_ac4_accepted(tmp_path, provider, disk):
    cfg = _load(tmp_path, _text(disk, provider))
    assert not [w for w in config_warnings(cfg) if "IOPS" in w]


@pytest.mark.story("CAP-060", "AC4")
def test_disk_types_ac4_below_recommended_warns(tmp_path):
    """Existing disks may have fewer IOPS than today's recommendation, so it is a warning, not an error."""
    cfg = _load(tmp_path, _text("disk: { type: gp3, storage: 500, iops: 3000 }"))
    assert any("3000 IOPS is below Capella's recommended 9850 for 500 GB" in w.what for w in config_warnings(cfg))
