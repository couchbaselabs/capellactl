"""CAP-022: the cluster's allowed CIDRs (IP allowlist) as code."""
from __future__ import annotations

import pytest
from freezegun import freeze_time

from capellactl.cli import console
from tests.conftest import MINIMAL, file_clusters, seed_healthy

CIDRS = """\
    allowedCidrs:
      - cidr: 203.0.113.10/32
        comment: Office VPN egress
      - cidr: 198.51.100.0/24
        comment: CI runners
        expiresAt: "2026-12-31T23:59:59Z"
"""
BASE = "/v4/organizations/org-1/projects/{pid}/clusters/{cid}/allowedcidrs"


def _seed_cidr(fake, cid, cidr, comment=None, **extra):
    i = f"cidr-{len(fake.cidrs) + 100}"
    fake.cidrs[i] = {"id": i, "_cluster": cid, "cidr": cidr, "status": "active",
                     **({"comment": comment} if comment else {}), **extra}
    return i


def _writes(fake):
    return [(c.method, c.path.rsplit("/allowedcidrs", 1)[-1], c.body) for c in fake.writes()]


@pytest.mark.story("CAP-022", "AC1")
def test_cidr_ac1_create_missing(fake, run, write_config):
    pid, cid = seed_healthy(fake)
    write_config(MINIMAL + CIDRS)
    r = run("plan")
    assert r.exit_code == 0, r.output
    assert '  + allowed-cidr nova-dev-01/203.0.113.10/32  "Office VPN egress" · permanent' in r.output
    assert '  + allowed-cidr nova-dev-01/198.51.100.0/24  "CI runners" · expires 2026-12-31T23:59:59Z' in r.output
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert [(c.method, c.path, c.body) for c in fake.writes()] == [
        ("POST", BASE.format(pid=pid, cid=cid), {"cidr": "203.0.113.10/32", "comment": "Office VPN egress"}),
        ("POST", BASE.format(pid=pid, cid=cid), {"cidr": "198.51.100.0/24", "comment": "CI runners",
                                                 "expiresAt": "2026-12-31T23:59:59Z"}),
    ]


@pytest.mark.story("CAP-022", "AC1")
def test_cidr_cli_ac1_create_records_and_applies(fake, run, write_config, tmp_path):
    _, cid = seed_healthy(fake)
    write_config(MINIMAL)
    r = run("--auto-approve", "cidr", "create", "nova-dev-01", "203.0.113.10", "--comment", "Office VPN")
    assert r.exit_code == 0, r.output
    assert [c.body for c in fake.writes()] == [{"cidr": "203.0.113.10/32", "comment": "Office VPN"}]
    assert file_clusters(tmp_path / "capella.yaml")[0]["allowedCidrs"] == [
        {"cidr": "203.0.113.10/32", "comment": "Office VPN"}]
    r = run("cidr", "list", "nova-dev-01")
    assert "203.0.113.10/32  Office VPN  never    active  yes" in r.output
    r = run("--auto-approve", "cidr", "create", "nova-dev-01", "10.0.0.5/24")
    assert r.exit_code == 3 and "10.0.0.5/24 is not a network address (did you mean 10.0.0.0/24?)" in r.output


@pytest.mark.story("CAP-022", "AC2")
def test_cidr_ac2_bare_ip_matches_32(fake, run, write_config):
    _, cid = seed_healthy(fake)
    _seed_cidr(fake, cid, "203.0.113.10/32", "Office VPN")
    write_config(MINIMAL + "    allowedCidrs:\n      - cidr: 203.0.113.10\n        comment: Office VPN\n")
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0, r.output
    assert "  = allowed-cidr nova-dev-01/203.0.113.10/32" in r.output


@pytest.mark.story("CAP-022", "AC3")
def test_cidr_ac3_replace_create_then_delete(fake, run, write_config):
    _, cid = seed_healthy(fake)
    old = _seed_cidr(fake, cid, "203.0.113.10/32", "a")
    fake.cidr_duplicates_allowed = True
    write_config(MINIMAL + "    allowedCidrs:\n      - cidr: 203.0.113.10/32\n        comment: b\n")
    r = run("plan")
    assert "  ± allowed-cidr nova-dev-01/203.0.113.10/32  (replace: API has no update)" in r.output
    assert '      comment:  "a" → "b"' in r.output
    assert "Plan: 1 to add, 0 to change, 0 to delete, 0 blocked." in r.output
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert _writes(fake) == [("POST", "", {"cidr": "203.0.113.10/32", "comment": "b"}), ("DELETE", f"/{old}", None)]
    assert [v["comment"] for v in fake.cidrs.values()] == ["b"]


@pytest.mark.story("CAP-022", "AC3")
def test_cidr_ac3_replace_fallback_on_409(fake, run, write_config):
    _, cid = seed_healthy(fake)
    old = _seed_cidr(fake, cid, "203.0.113.10/32", "a")
    write_config(MINIMAL + "    allowedCidrs:\n      - cidr: 203.0.113.10/32\n        comment: b\n")
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    assert "warning: access from 203.0.113.10/32 is briefly interrupted" in r.output
    body = {"cidr": "203.0.113.10/32", "comment": "b"}
    assert _writes(fake) == [("POST", "", body), ("DELETE", f"/{old}", None), ("POST", "", body)]
    assert [v["comment"] for v in fake.cidrs.values()] == ["b"]


@pytest.mark.story("CAP-022", "AC4")
def test_cidr_ac4_unmanaged_not_deleted(fake, run, write_config, monkeypatch):
    _, cid = seed_healthy(fake)
    _seed_cidr(fake, cid, "203.0.113.10/32", "Office VPN egress")
    stray = _seed_cidr(fake, cid, "192.0.2.7/32", "old laptop")
    write_config(MINIMAL + "    allowedCidrs:\n      - cidr: 203.0.113.10/32\n        comment: Office VPN egress\n")
    r = run("plan")
    assert r.exit_code == 0, r.output
    assert ('Unmanaged (not in capella.yaml; use --prune to delete):\n    allowed-cidr nova-dev-01/192.0.2.7/32  '
            '"old laptop"') in r.output
    assert run("--auto-approve", "apply").exit_code == 0
    assert fake.writes() == []
    r = run("-o", "json", "plan")
    assert '"unmanaged"' in r.output
    r = run("--auto-approve", "apply", "--prune")
    assert r.exit_code == 0, r.output
    assert "  - allowed-cidr nova-dev-01/192.0.2.7/32" in r.output
    assert _writes(fake) == [("DELETE", f"/{stray}", None)]


@pytest.mark.story("CAP-022", "AC4")
def test_cidr_ac4_unmanaged_listed_when_file_has_none(fake, run, write_config):
    _, cid = seed_healthy(fake)
    _seed_cidr(fake, cid, "192.0.2.7/32")
    write_config(MINIMAL)
    r = run("plan", "--detailed-exitcode")
    assert r.exit_code == 0, r.output  # listing is not a change
    assert "    allowed-cidr nova-dev-01/192.0.2.7/32" in r.output


@pytest.mark.story("CAP-022", "AC5")
def test_cidr_ac5_any_ip_warning(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL + "    allowAnyIp: true\n    allowedCidrs:\n      - cidr: 0.0.0.0/0\n")
    r = run("plan")
    assert r.exit_code == 0, r.output
    assert "warning: allowed CIDR 0.0.0.0/0 on nova-dev-01 lets any IP address connect (allowAnyIp: true)" in r.output
    assert "  + allowed-cidr nova-dev-01/0.0.0.0/0" in r.output


@pytest.mark.story("CAP-022", "AC6")
def test_cidr_ac6_past_expiry_warning_and_no_recreate(fake, run, write_config):
    seed_healthy(fake)  # the fake clock reads 2026-10-05
    write_config(MINIMAL + "    allowedCidrs:\n      - cidr: 198.51.100.0/24\n        expiresAt: \"2026-01-01T00:00:00Z\"\n"
                           "      - cidr: 203.0.113.10/32\n        expiresAt: \"2027-01-01T00:00:00Z\"\n")
    with freeze_time("2026-10-05T17:00:00Z"):
        r = run("validate")
    assert r.exit_code == 0, r.output
    assert ("warning: clusters[0].allowedCidrs[0].expiresAt: expiresAt is in the past; Capella will remove it "
            "(line 20)") in r.output
    assert "allowedCidrs[1]" not in r.output
    with freeze_time("2026-10-05T17:00:00Z"):
        r = run("plan")
    assert "  = allowed-cidr nova-dev-01/198.51.100.0/24  (expiresAt is in the past; Capella removed it, not " \
           "re-created)" in r.output
    assert "  + allowed-cidr nova-dev-01/203.0.113.10/32" in r.output
    assert "Plan: 1 to add" in r.output


@pytest.mark.story("CAP-022", "AC7")
def test_cidr_cli_ac7_delete_and_absent(fake, run, write_config, tmp_path, monkeypatch):
    _, cid = seed_healthy(fake)
    i = _seed_cidr(fake, cid, "203.0.113.10/32", "Office VPN")
    write_config(MINIMAL + "    allowedCidrs:\n      - cidr: 203.0.113.10/32\n        comment: Office VPN\n")
    r = run("cidr", "delete", "nova-dev-01", "203.0.113.10/32")
    assert r.exit_code == 1 and fake.writes() == []  # no terminal and no --auto-approve
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cidr", "delete", "nova-dev-01", "203.0.113.10", input="y\n")
    assert r.exit_code == 0, r.output
    assert "deleted allowed CIDR 203.0.113.10/32 from nova-dev-01" in r.output
    assert _writes(fake) == [("DELETE", f"/{i}", None)]
    assert "allowedCidrs" not in file_clusters(tmp_path / "capella.yaml")[0]
    fake.reset_calls()
    r = run("--auto-approve", "cidr", "delete", "nova-dev-01", "203.0.113.10/32")
    assert r.exit_code == 0 and "not found, nothing to do" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-022", "AC8")
def test_cidr_ac8_rerun_zero_writes(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL + CIDRS)
    assert run("--auto-approve", "apply").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0 and "No changes" in r.output, r.output
    assert fake.writes() == []
