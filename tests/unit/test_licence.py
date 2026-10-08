"""CAP-044: licence, notices and third-party attributions."""
from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APACHE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"  # apache.org LICENSE-2.0.txt


def _script():
    spec = importlib.util.spec_from_file_location("third_party_notices", ROOT / "scripts" / "third-party-notices.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses look their module up here
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.story("CAP-044", "AC1")
def test_licence_ac1_file_matches_pyproject():
    text = (ROOT / "LICENSE").read_bytes()
    assert hashlib.sha256(text).hexdigest() == APACHE_SHA256  # the unmodified Apache License 2.0
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert re.search(r'^license = "Apache-2.0"$', pyproject, re.M)
    assert 'license-files = ["LICENSE", "NOTICE"]' in pyproject
    from capellactl import LICENSE

    assert LICENSE == "Apache-2.0"


@pytest.mark.story("CAP-044", "AC2")
def test_licence_ac2_notice_and_version_line(run):
    notice = (ROOT / "NOTICE").read_text()
    assert notice.splitlines()[:3] == ["capellactl", "Copyright 2026 Couchbase, Inc.",
                                       "Author: Anuj Sahni, Principal Cloud & Solutions Architect"]
    assert "Apache License, Version 2.0" in notice and "THIRD_PARTY_NOTICES.md" in notice
    r = run("--version")
    assert r.exit_code == 0
    assert r.output.splitlines()[1] == "Licensed under Apache-2.0 · Copyright 2026 Couchbase, Inc."


@pytest.mark.story("CAP-044", "AC3")
def test_licence_ac3_third_party_notices_current():
    tpn = _script()
    text = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    installed = tpn.collect(offline=True)
    assert {"click", "requests", "pyyaml", "jsonschema", "rich", "keyring", "ruamel-yaml"} <= {
        tpn.canonicalize_name(d.name) for d in installed}
    assert tpn.check(text, installed, tpn.load_policy()) == []


@pytest.mark.story("CAP-044", "AC3")
def test_licence_ac3_stale_file_detected():
    tpn = _script()
    installed = tpn.collect(offline=True)
    text = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    without_click = "\n".join(line for line in text.splitlines() if not line.startswith("| click |"))
    assert any("click" in p and "not in THIRD_PARTY_NOTICES.md" in p
               for p in tpn.check(without_click, installed, tpn.load_policy()))
    relicensed = text.replace("| click | ", "| click | 0 | GPL-3.0-only |  |  |\n| clickx | ", 1)
    assert any("click: THIRD_PARTY_NOTICES.md says GPL-3.0-only" in p
               for p in tpn.check(relicensed, installed, tpn.load_policy()))


@pytest.mark.story("CAP-044", "AC4")
def test_licence_ac4_policy_rejects_unknown_licence():
    tpn = _script()
    policy = tpn.load_policy()
    gpl = tpn.Dep("copyleft-lib", "1.0", "GPL-3.0-only", "", "")
    unknown = tpn.Dep("mystery-lib", "0.1", tpn.licence_from(None, None, []), "", "")
    assert unknown.licence == "UNKNOWN"
    rows = tpn.render([gpl, unknown])
    problems = tpn.check(rows, [gpl, unknown], policy)
    assert "copyleft-lib 1.0 is licensed GPL-3.0-only, which is not allowed by scripts/licence-policy.json" in problems
    assert "mystery-lib 0.1 is licensed UNKNOWN, which is not allowed by scripts/licence-policy.json" in problems


@pytest.mark.story("CAP-044", "AC4")
@pytest.mark.parametrize(("expression", "ok"), [
    ("MIT", True), ("Apache-2.0 OR BSD-3-Clause", True), ("GPL-2.0-only OR MIT", True),
    ("MIT AND (Apache-2.0 OR BSD-2-Clause)", True), ("MIT AND GPL-3.0-only", False), ("LGPL-3.0-or-later", False),
    ("Apache-2.0 WITH LLVM-exception", True),
])
def test_licence_ac4_spdx_expressions(expression, ok):
    tpn = _script()
    assert tpn.allowed(expression, tpn.load_policy()) is ok


@pytest.mark.story("CAP-044", "AC4")
def test_licence_ac4_metadata_normalisation():
    tpn = _script()
    assert tpn.licence_from("BSD-3-Clause", None, []) == "BSD-3-Clause"
    assert tpn.licence_from(None, "MIT License", []) == "MIT"
    assert tpn.licence_from(None, "Permission is hereby granted...\n" * 3,
                            ["License :: OSI Approved :: Apache Software License"]) == "Apache-2.0"
