"""CAP-022: allowed-CIDR rules in `validate` (offline)."""
from __future__ import annotations

import textwrap

import pytest

from capellactl.config.loader import ConfigError, load_config
from tests.conftest import MINIMAL


def _load(tmp_path, extra):
    p = tmp_path / "capella.yaml"
    p.write_text(textwrap.dedent(MINIMAL) + extra, encoding="utf-8")
    return load_config(p, env={"CAPELLA_ORG_ID": "org-1"})


def _error(tmp_path, extra):
    with pytest.raises(ConfigError) as exc:
        _load(tmp_path, extra)
    return str(exc.value)


@pytest.mark.story("CAP-022", "AC2")
def test_cidr_validate_ac2_host_bits_rejected(tmp_path):
    msg = _error(tmp_path, "    allowedCidrs:\n      - cidr: 10.0.0.5/24\n")
    assert "clusters[0].allowedCidrs[0].cidr: 10.0.0.5/24 is not a network address (did you mean 10.0.0.0/24?)" in msg


@pytest.mark.story("CAP-022", "AC2")
def test_cidr_validate_ac2_cli_exit_3(tmp_path, run):
    (tmp_path / "capella.yaml").write_text(textwrap.dedent(MINIMAL) + "    allowedCidrs:\n      - cidr: 10.0.0.5/24\n", encoding="utf-8")
    r = run("validate")
    assert r.exit_code == 3 and "did you mean 10.0.0.0/24?" in r.output


@pytest.mark.story("CAP-022", "AC5")
def test_cidr_validate_ac5_any_ip_requires_flag(tmp_path):
    msg = _error(tmp_path, "    allowedCidrs:\n      - cidr: 0.0.0.0/0\n")
    assert "0.0.0.0/0 allows every IP address; set allowAnyIp: true on the cluster to confirm" in msg
    cfg = _load(tmp_path, "    allowAnyIp: true\n    allowedCidrs:\n      - cidr: 0.0.0.0/0\n")
    assert cfg.counts()["allowed CIDR"] == 1


@pytest.mark.story("CAP-022", "AC6")
def test_cidr_validate_ac6_expires_at_format(tmp_path):
    msg = _error(tmp_path, "    allowedCidrs:\n      - cidr: 203.0.113.10/32\n        expiresAt: next tuesday\n")
    assert "next tuesday is not an RFC 3339 time" in msg
