"""CAP-027: credential rules in `validate` (offline)."""
from __future__ import annotations

import textwrap

import pytest

from capellactl.config.loader import ConfigError, load_config
from tests.conftest import MINIMAL

BUCKET = "    buckets:\n      - name: orders\n"


def _write(tmp_path, privileges):
    p = tmp_path / "capella.yaml"
    p.write_text(textwrap.dedent(MINIMAL) + BUCKET + "    databaseCredentials:\n      - name: orders_app\n"
                 f"        access:\n          - privileges: [{privileges}]\n"
                 "            resources: { buckets: [ { name: orders } ] }\n", encoding="utf-8")
    return p


@pytest.mark.story("CAP-027", "AC6")
def test_credential_validate_ac6_privilege_rejected(tmp_path, run):
    with pytest.raises(ConfigError) as exc:
        load_config(_write(tmp_path, "queryManage"), env={"CAPELLA_ORG_ID": "org-1"})
    assert ("clusters[0].databaseCredentials[0].access[0].privileges[0]: basic credentials support read/write only; "
            "advanced credentials are planned for 1.1") in str(exc.value)
    r = run("validate")
    assert r.exit_code == 3 and "advanced credentials are planned for 1.1" in r.output


@pytest.mark.story("CAP-027", "AC6")
def test_credential_validate_ac6_basic_privileges_accepted(tmp_path):
    cfg = load_config(_write(tmp_path, "read, data_writer"), env={"CAPELLA_ORG_ID": "org-1"})
    assert cfg.counts()["credential"] == 1
