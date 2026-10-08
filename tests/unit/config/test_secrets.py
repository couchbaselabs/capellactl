"""CAP-002 AC2, AC3: secret references."""
from __future__ import annotations

import pytest

from capellactl.config.loader import ConfigError, load_config
from capellactl.output.redact import redactor
from tests.conftest import MINIMAL, assert_no_secret

CRED = """
    buckets:
      - name: orders
        memoryAllocationInMb: 1024
    databaseCredentials:
      - name: app
        password: {pw}
        access:
          - privileges: [read]
            resources: {{ buckets: [ {{ name: orders }} ] }}
"""
SECRET = "S3cret!Value-xyz"


def _write(tmp_path, pw: str):
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL + CRED.format(pw=pw))
    return p


@pytest.mark.story("CAP-002", "AC2")
def test_loader_ac2_env_reference_resolved(tmp_path):
    cfg = load_config(_write(tmp_path, "${APP_PW}"), env={"CAPELLA_ORG_ID": "o", "APP_PW": SECRET})
    assert cfg.clusters[0]["databaseCredentials"][0]["password"] == SECRET
    assert SECRET in redactor.values


@pytest.mark.story("CAP-002", "AC2")
def test_loader_ac2_unset_env_names_variable(tmp_path):
    with pytest.raises(ConfigError) as ei:
        load_config(_write(tmp_path, "${APP_PW}"), env={"CAPELLA_ORG_ID": "o"})
    assert "clusters[0].databaseCredentials[0].password: environment variable APP_PW is not set" in str(ei.value)


@pytest.mark.story("CAP-002", "AC2")
def test_loader_ac2_file_reference_resolved_relative_to_config(tmp_path):
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "pw.txt").write_text(SECRET + "\n")
    cfg = load_config(_write(tmp_path, "${file:./secrets/pw.txt}"), env={"CAPELLA_ORG_ID": "o"})
    assert cfg.clusters[0]["databaseCredentials"][0]["password"] == SECRET


@pytest.mark.story("CAP-002", "AC2")
def test_loader_ac2_missing_file_names_path(tmp_path):
    with pytest.raises(ConfigError) as ei:
        load_config(_write(tmp_path, "${file:./secrets/none.txt}"), env={"CAPELLA_ORG_ID": "o"})
    assert "file ./secrets/none.txt not found" in str(ei.value)


@pytest.mark.story("CAP-002", "AC2")
def test_loader_ac2_errors_never_contain_value(tmp_path):
    # A schema error elsewhere in the file must not echo the resolved secret.
    p = tmp_path / "c.yaml"
    p.write_text((MINIMAL + CRED.format(pw="${APP_PW}")).replace("numOfNodes: 3", "numOfNodes: 99"))
    with pytest.raises(ConfigError) as ei:
        load_config(p, env={"CAPELLA_ORG_ID": "o", "APP_PW": SECRET})
    assert_no_secret(str(ei.value), SECRET)


@pytest.mark.story("CAP-002", "AC3")
def test_loader_ac3_literal_password_rejected(tmp_path):
    with pytest.raises(ConfigError) as ei:
        load_config(_write(tmp_path, "Sup3r$ecret"), env={"CAPELLA_ORG_ID": "o"})
    text = str(ei.value)
    assert "passwords must be supplied via ${VAR} or ${file:...}" in text
    assert_no_secret(text, "Sup3r$ecret")
