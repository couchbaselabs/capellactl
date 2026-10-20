"""CAP-008 AC2, AC3: generated password files."""
from __future__ import annotations

import json
import os
import stat

import pytest

from capellactl.output.redact import redactor
from capellactl.output.secrets_out import (
    SecretFileExists,
    preflight,
    saved_message,
    write_generated_credential,
)


@pytest.mark.story("CAP-008", "AC2")
def test_secrets_out_ac2_file_mode_and_content(tmp_path):
    p = write_generated_credential(tmp_path / ".capellactl" / "credentials", "nova-dev-01", "web_sessions", "u-1",
                                   "Gen3rated!Pw-1")
    assert p.name == "nova-dev-01.web_sessions.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert set(data) == {"cluster", "name", "id", "password", "createdAt"} and data["password"] == "Gen3rated!Pw-1"
    if os.name == "posix":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    assert "Gen3rated!Pw-1" in redactor.values


@pytest.mark.story("CAP-008", "AC2")
def test_secrets_out_ac2_terminal_shows_path_only(tmp_path):
    p = write_generated_credential(tmp_path, "c", "n", "u-1", "Gen3rated!Pw-2")
    msg = saved_message(p)
    assert msg == f"password saved to {p}"
    assert "Gen3rated!Pw-2" not in msg


@pytest.mark.story("CAP-008", "AC3")
def test_secrets_out_ac3_preflight_refuses_overwrite(tmp_path):
    write_generated_credential(tmp_path, "c", "n", "u-1", "Gen3rated!Pw-3")
    with pytest.raises(SecretFileExists, match="refusing to overwrite .*; move it or pass --force-overwrite-secret"):
        preflight(tmp_path, "c", "n")
    assert preflight(tmp_path, "c", "n", force=True).exists()
    with pytest.raises(SecretFileExists):
        write_generated_credential(tmp_path, "c", "n", "u-1", "Another!Pw-4")
    assert json.loads((tmp_path / "c.n.json").read_text(encoding="utf-8"))["password"] == "Gen3rated!Pw-3"
