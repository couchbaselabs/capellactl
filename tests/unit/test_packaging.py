"""CAP-001 AC6: container image definition (the image itself is built and measured in CI: image-smoke)."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.story("CAP-001", "AC6")
def test_image_ac6_dockerfile_non_root_entrypoint():
    text = (ROOT / "Dockerfile").read_text()
    assert "USER 10001" in text
    assert 'ENTRYPOINT ["capellactl"]' in text
    assert "python:3.12-slim" in text
    assert "pip uninstall -y -q pip" in text  # keep the runtime image small


@pytest.mark.story("CAP-001", "AC6")
def test_image_ac6_ci_checks_size_and_user():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "image-smoke" in ci and "52428800" in ci and "--entrypoint id capellactl:ci -u" in ci


@pytest.mark.story("CAP-044", "AC5")
def test_licence_ac5_wheel_metadata(tmp_path):
    import subprocess
    import sys
    import zipfile

    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-q", "-w",
                    str(tmp_path), str(ROOT)], check=True)
    wheel = next(tmp_path.glob("capellactl-*.whl"))
    with zipfile.ZipFile(wheel) as z:
        names = z.namelist()
        meta = z.read(next(n for n in names if n.endswith(".dist-info/METADATA"))).decode()
    assert "License-Expression: Apache-2.0" in meta.splitlines()
    assert {"License-File: LICENSE", "License-File: NOTICE"} <= set(meta.splitlines())
    assert any(n.endswith(".dist-info/licenses/LICENSE") for n in names)
    assert any(n.endswith(".dist-info/licenses/NOTICE") for n in names)
