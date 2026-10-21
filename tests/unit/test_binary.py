"""CAP-045: executable names, the downloads/ folder and the README Download section."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.integration.harness import load_script

build = load_script("build-binary")
dl = load_script("update-downloads")
ROOT = Path(__file__).resolve().parents[2]
FILES = ["capellactl-1.0.0-macos-arm64", "capellactl-1.0.0-macos-x86_64", "capellactl-1.0.0-linux-x86_64",
         "capellactl-1.0.0-linux-arm64", "capellactl-1.0.0-windows-x86_64.exe"]


@pytest.mark.story("CAP-045", "AC1")
@pytest.mark.parametrize("system,machine,name", [
    ("Darwin", "arm64", "capellactl-1.0.0-macos-arm64"), ("Darwin", "x86_64", "capellactl-1.0.0-macos-x86_64"),
    ("Linux", "x86_64", "capellactl-1.0.0-linux-x86_64"), ("Linux", "aarch64", "capellactl-1.0.0-linux-arm64"),
    ("Windows", "AMD64", "capellactl-1.0.0-windows-x86_64.exe"), ("Windows", "ARM64", "capellactl-1.0.0-windows-arm64.exe"),
])
def test_binary_ac1_name_for_platform(system, machine, name):
    assert build.binary_name("1.0.0", system, machine) == name


@pytest.mark.story("CAP-045", "AC1")
@pytest.mark.parametrize("system,machine", [("Linux", "armv7l"), ("FreeBSD", "amd64"), ("Linux", "i686")])
def test_binary_ac1_unsupported_platform(system, machine):
    with pytest.raises(build.BuildError, match="no standalone executable"):
        build.binary_name("1.0.0", system, machine)


@pytest.fixture
def release(tmp_path, monkeypatch):
    """A repository copy: README.md, an empty downloads/ and the five executables of release 1.0.0."""
    files = tmp_path / "release"
    files.mkdir()
    for i, name in enumerate(FILES):
        (files / name).write_bytes(bytes([i]) * (1000 + i))
    (tmp_path / "downloads").mkdir()
    (tmp_path / "README.md").write_text((ROOT / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(dl, "ROOT", tmp_path)
    monkeypatch.setattr(dl, "DOWNLOADS", tmp_path / "downloads")
    monkeypatch.setattr(dl, "README", tmp_path / "README.md")
    return tmp_path, files


@pytest.mark.story("CAP-045", "AC3")
def test_binary_ac3_downloads_folder_contents(release):
    root, files = release
    assert dl.main(["--from", str(files)]) == 0 and dl.main(["--check"]) == 0
    assert {p.name for p in (root / "downloads").iterdir()} == {"README.md", "SHA256SUMS", "manifest.json"}
    manifest = json.loads((root / "downloads" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.0.0" and [f["file"] for f in manifest["files"]] == sorted(FILES)
    lines = (root / "downloads" / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert [line.split("  ")[1] for line in lines] == FILES  # the README's order
    for line in lines:  # shasum -a 256 -c SHA256SUMS passes
        digest, name = line.split("  ")
        assert dl.sha256(files / name) == digest


@pytest.mark.story("CAP-045", "AC3")
def test_binary_ac3_dry_run_dev_version(release):
    root, files = release
    dev = "1.0.0.dev7+g3b456ff"  # what a manual run of the release workflow builds
    for p in list(files.iterdir()):
        p.rename(files / p.name.replace("1.0.0", dev))
    assert dl.main(["--from", str(files)]) == 0 and dl.main(["--check"]) == 0
    assert json.loads((root / "downloads" / "manifest.json").read_text(encoding="utf-8"))["version"] == dev


@pytest.mark.story("CAP-045", "AC3")
@pytest.mark.parametrize("change,problem", [
    (lambda m: m["files"].pop(), "no executable for windows-x86_64"),
    (lambda m: m["files"].append({**m["files"][0]}), "more than one executable"),
    (lambda m: m["files"][0].update(file="capellactl-0.9.0-macos-arm64"), "version 0.9.0, the release is 1.0.0"),
    (lambda m: m["files"][0].update(sha256="x"), "no SHA-256"),
])
def test_binary_ac3_incomplete_release_fails(release, change, problem):
    _, files = release
    m = dl.manifest_from(files)
    change(m)
    assert any(problem in p for p in dl.problems(m, set(dl.KEPT))), dl.problems(m, set(dl.KEPT))


@pytest.mark.story("CAP-045", "AC3")
def test_binary_ac3_executables_are_not_kept_in_git(release):
    root, files = release
    assert dl.main(["--from", str(files)]) == 0
    (root / "downloads" / FILES[0]).write_bytes(b"old")  # an executable from an earlier release
    assert dl.main(["--check"]) == 1


@pytest.mark.story("CAP-045", "AC4")
def test_binary_ac4_readme_download_table(release, capsys):
    root, files = release
    assert dl.main(["--from", str(files)]) == 0
    readme = (root / "README.md").read_text(encoding="utf-8")
    block = readme.split(dl.START)[1].split(dl.END)[0]
    m = dl.manifest_from(files)
    for f in m["files"]:
        url = f"https://github.com/couchbaselabs/capellactl/releases/download/v1.0.0/{f['file']}"
        row = next(line for line in block.splitlines() if f["file"] in line)
        assert url in row and f["sha256"][:12] in row and dl.PLATFORMS[(f["os"], f["arch"])] in row
    assert readme.index("## Download") < readme.index(dl.START) < readme.index("## Install")
    page = (root / "downloads" / "README.md").read_text(encoding="utf-8")
    for words in ("chmod +x", "Get-FileHash", "uname -m", "About This Mac", "shasum -a 256 -c"):
        assert words in page, words


@pytest.mark.story("CAP-045", "AC4")
@pytest.mark.parametrize("drift", ["missing file", "extra file", "stale checksum", "readme"])
def test_binary_ac4_check_detects_drift(release, drift, capsys):
    root, files = release
    assert dl.main(["--from", str(files)]) == 0
    mpath = root / "downloads" / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    if drift == "missing file":
        m["files"] = m["files"][1:]
    elif drift == "extra file":
        m["files"].append({**m["files"][0], "file": "capellactl-1.0.0-macos-arm64.old"})
    elif drift == "stale checksum":
        m["files"][0]["sha256"] = "0" * 64
    if drift == "readme":
        p = root / "README.md"
        p.write_text(p.read_text(encoding="utf-8").replace(" MB |", " GB |", 1), encoding="utf-8")
    else:
        mpath.write_text(json.dumps(m), encoding="utf-8")
    assert dl.main(["--check"]) == 1


def _release():
    import yaml

    return yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))["jobs"]


@pytest.mark.story("CAP-045", "AC1")
def test_binary_ac1_release_builds_five_platforms():
    jobs = _release()
    names = [m["name"] for job in ("binary", "binary-linux") for m in jobs[job]["strategy"]["matrix"]["include"]]
    assert sorted(names) == sorted(f"{o}-{a}" for o, a in dl.PLATFORMS)
    runners = {m["runs-on"] for m in jobs["binary"]["strategy"]["matrix"]["include"]}
    assert "macos-13" not in runners and {"macos-15", "macos-15-intel"} <= runners  # macos-13 is retired
    assert jobs["binary-linux"]["container"] == "almalinux:8"  # glibc 2.28 on both Linux architectures
    steps = "\n".join(str(s.get("run", "")) for s in jobs["downloads"]["steps"])
    assert 'ls executables | wc -l)" -eq 5' in steps and "update-downloads.py --check" in steps


@pytest.mark.story("CAP-045", "AC6")
def test_binary_ac6_release_signs_or_fails():
    steps = _release()["binary"]["steps"]
    by_name = {s.get("name", ""): s for s in steps}
    assert "xcrun notarytool submit" in by_name["notarize (macOS, AC6)"]["run"]
    assert "Get-AuthenticodeSignature" in by_name["sign (Windows, AC6)"]["run"]
    gate = by_name["a release tag needs signed executables (AC6)"]
    assert gate["if"] == "github.event_name == 'push' && vars.ALLOW_UNSIGNED != 'true'" and "exit 1" in gate["run"]
    order = [s.get("name", "") for s in steps]
    assert order.index("build (make binary)") < order.index("notarize (macOS, AC6)") \
        < order.index("smoke tests on the final file (AC2, AC5, AC7, AC8)")  # the smoke tests run on the signed file
    spec = (ROOT / "capellactl.spec").read_text(encoding="utf-8")
    assert "codesign_identity=identity" in spec and "entitlements.plist" in spec


@pytest.mark.story("CAP-045", "AC4")
def test_binary_ac4_repository_is_up_to_date():
    """The real downloads/ and README block match: before the first release, the 'not released yet' table."""
    assert dl.main(["--check"]) == 0
