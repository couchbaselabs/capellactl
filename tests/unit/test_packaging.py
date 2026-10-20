"""CAP-001 AC6: container image definition (the image itself is built and measured in CI: image-smoke)."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.story("CAP-001", "AC6")
def test_image_ac6_dockerfile_non_root_entrypoint():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER 10001" in text
    assert 'ENTRYPOINT ["capellactl"]' in text
    assert "python:3.12-slim" in text
    assert "pip uninstall -y -q pip" in text  # keep the runtime image small


@pytest.mark.story("CAP-001", "AC6")
def test_image_ac6_ci_checks_size_and_user():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
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


# ------------------------------------------------------------------ CAP-043: make dist
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tarfile  # noqa: E402
import zipfile  # noqa: E402

from tests.conftest import child_env  # noqa: E402

IGNORE = shutil.ignore_patterns(".venv", ".git", "dist", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                                "*.swp", ".capellactl", "capella.yaml*", "CLAUDE.md", ".claude", "*.egg-info")
SECRET = f"never-shipped-{os.getpid()}-{id(object())}"  # made at run time: this file itself ships in the sdist
LOCAL_FILES = {"capella.yaml": "organizationId: org-1\n", "capella.yaml.bak": "old\n",
               ".capellactl/credentials/c.app.json": f'{{"password": "{SECRET}"}}\n', "secrets/pw.txt": SECRET,
               "CLAUDE.md": SECRET, ".env": f"CAPELLA_API_KEY={SECRET}\n"}


def _git(tree: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                           *args], cwd=tree, check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def _dist(tree: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(tree / "scripts" / "build-dist.py"), "--outdir", str(out)],
                          cwd=tree, capture_output=True, text=True, encoding="utf-8")


def _members(archive: Path) -> list[str]:
    if archive.suffix == ".whl":
        with zipfile.ZipFile(archive) as z:
            return z.namelist()
    with tarfile.open(archive) as t:
        return [m.name.split("/", 1)[1] for m in t.getmembers() if m.isfile()]


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    """A clean checkout of this source tree (a git repo with one commit) plus local, never-shipped files."""
    t = tmp_path_factory.mktemp("src") / "capellactl"
    shutil.copytree(ROOT, t, ignore=IGNORE)
    _git(t, "init", "-q")
    _git(t, "add", "-A")
    _git(t, "commit", "-q", "-m", "release candidate")
    for rel, text in LOCAL_FILES.items():
        (t / rel).parent.mkdir(parents=True, exist_ok=True)
        (t / rel).write_text(text, encoding="utf-8")
    return t


@pytest.fixture(scope="module")
def built(tree, tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    r = _dist(tree, out)
    assert r.returncode == 0, r.stdout + r.stderr
    return out


@pytest.mark.story("CAP-043", "AC1")
def test_dist_ac1_make_dist_outputs(built):
    names = sorted(p.name for p in built.iterdir())
    assert len(names) == 3 and "SHA256SUMS" in names
    assert any(n.endswith(".tar.gz") for n in names) and any(n.endswith("-py3-none-any.whl") for n in names)
    for line in (built / "SHA256SUMS").read_text(encoding="utf-8").splitlines():  # sha256sum -c
        digest, name = line.split("  ")
        assert hashlib.sha256((built / name).read_bytes()).hexdigest() == digest
    assert "dist:" in (ROOT / "Makefile").read_text(encoding="utf-8") and "scripts/build-dist.py" in (ROOT / "Makefile").read_text(encoding="utf-8")


@pytest.mark.story("CAP-043", "AC2")
@pytest.mark.parametrize("kind", ["tar.gz", "whl"])
def test_dist_ac2_install_from_sdist(built, tmp_path, kind):
    archive = next(built.glob(f"*.{kind}"))
    target = tmp_path / "site"
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "--no-build-isolation", "--target",
                    str(target), str(archive)], check=True, capture_output=True)
    shutil.copy(ROOT / "docs" / "release-1.0.0" / "examples" / "minimal-cluster.yaml", tmp_path / "capella.yaml")
    env = child_env(PATH=os.environ.get("PATH", ""), PYTHONPATH=str(target), HOME=str(tmp_path),
                    CAPELLACTL_HOME=str(tmp_path / "home"), CAPELLA_ORG_ID="org-1")

    def cap(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-m", "capellactl", *args], cwd=tmp_path, env=env, capture_output=True,
                              text=True, encoding="utf-8")

    probe = subprocess.run([sys.executable, "-c", "import capellactl; print(capellactl.__file__)"], env=env,
                           capture_output=True, text=True, encoding="utf-8")
    where = probe.stdout
    assert where.startswith(str(target)), where + probe.stderr  # the installed copy, not this source tree
    version = archive.name.removeprefix("capellactl-").split("-py3")[0].removesuffix(".tar.gz")
    assert cap("--version").stdout.startswith(f"capellactl {version} ")
    assert "getting-started" in cap("help", "topics").stdout
    r = cap("validate")
    assert r.returncode == 0 and "Configuration valid" in r.stdout, r.stdout + r.stderr


@pytest.mark.story("CAP-043", "AC3")
def test_dist_ac3_no_local_files_in_archives(built):
    for archive in [*built.glob("*.tar.gz"), *built.glob("*.whl")]:
        members = _members(archive)
        for rel in LOCAL_FILES:
            assert rel not in members, f"{rel} shipped in {archive.name}"
        assert not [m for m in members if "/secrets/" in f"/{m}" or m.startswith(".capellactl")]
        assert not any(SECRET.encode() in data for data in _contents(archive))


def _contents(archive: Path) -> list[bytes]:
    if archive.suffix == ".whl":
        with zipfile.ZipFile(archive) as z:
            return [z.read(n) for n in z.namelist()]
    with tarfile.open(archive) as t:
        return [t.extractfile(m).read() for m in t.getmembers() if m.isfile()]  # type: ignore[union-attr]


def _build_dist_module():
    spec = importlib.util.spec_from_file_location("build_dist", ROOT / "scripts" / "build-dist.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.story("CAP-043", "AC3")
def test_dist_ac3_archive_outside_allowlist_fails(tmp_path):
    bd = _build_dist_module()
    sdist = tmp_path / "capellactl-1.0.0.tar.gz"
    files = {"LICENSE": "", "NOTICE": "", "THIRD_PARTY_NOTICES.md": "", "CHANGELOG.md": "",
             "capellactl/config/schema.json": "{}", "docs/secrets/pw.txt": "x", "capella.yaml": "x", "notes.txt": "x"}
    with tarfile.open(sdist, "w:gz") as t:
        for rel, text in files.items():
            p = tmp_path / "src" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            t.add(p, arcname=f"capellactl-1.0.0/{rel}")
    problems = bd.check_sdist(sdist)
    assert any("docs/secrets/pw.txt must never ship" in p for p in problems)
    assert any("capella.yaml" in p for p in problems)
    assert any("notes.txt is not in the source-archive allowlist" in p for p in problems)


@pytest.mark.story("CAP-043", "AC4")
def test_dist_ac4_license_files(built):
    sdist = _members(next(built.glob("*.tar.gz")))
    assert {"LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"} <= set(sdist)
    wheel = _members(next(built.glob("*.whl")))
    assert any(n.endswith(".dist-info/licenses/LICENSE") for n in wheel)
    assert any(n.endswith(".dist-info/licenses/NOTICE") for n in wheel)
    r = subprocess.run([sys.executable, "-m", "twine", "check", "--strict", *map(str, built.glob("capellactl-*"))],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.story("CAP-043", "AC5")
def test_dist_ac5_version_from_tag(tree, built, tmp_path):
    sha = _git(tree, "rev-parse", "--short=7", "HEAD")
    assert next(built.glob("*.whl")).name == f"capellactl-1.0.0.dev1+g{sha}-py3-none-any.whl"  # untagged
    _git(tree, "tag", "v1.0.0")
    r = _dist(tree, tmp_path / "no-changelog")
    assert r.returncode == 1 and "CHANGELOG.md has no '## 1.0.0' section" in r.stderr
    _git(tree, "tag", "-d", "v1.0.0")
    changelog = tree / "CHANGELOG.md"
    changelog.write_text(changelog.read_text(encoding="utf-8").replace("## Unreleased", "## 1.0.0 — 2026-10-08"), encoding="utf-8")
    _git(tree, "commit", "-q", "-am", "1.0.0")
    _git(tree, "tag", "v1.0.0")
    out = tmp_path / "tagged"
    r = _dist(tree, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(p.name for p in out.iterdir()) == ["SHA256SUMS", "capellactl-1.0.0-py3-none-any.whl",
                                                     "capellactl-1.0.0.tar.gz"]
    with zipfile.ZipFile(out / "capellactl-1.0.0-py3-none-any.whl") as z:
        meta = z.read("capellactl-1.0.0.dist-info/METADATA").decode()
    assert "Version: 1.0.0" in meta.splitlines()
    (tree / "README.md").write_text((tree / "README.md").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    _git(tree, "commit", "-q", "-am", "after the release")
    after = subprocess.run([sys.executable, str(tree / "scripts" / "version.py")], capture_output=True, text=True, encoding="utf-8")
    assert after.stdout.strip() == f"1.0.1.dev1+g{_git(tree, 'rev-parse', '--short=7', 'HEAD')}"
    _git(tree, "checkout", "-q", "v1.0.0")


@pytest.mark.story("CAP-043", "AC6")
def test_dist_ac6_reproducible_build(tree, tmp_path):
    _git(tree, "checkout", "-q", "v1.0.0")  # tagged by the AC5 test (pytest runs a module's tests in order)
    first, second = tmp_path / "a", tmp_path / "b"
    assert _dist(tree, first).returncode == 0
    os.utime(tree / "README.md")  # a later checkout: file times differ, the archives must not
    assert _dist(tree, second).returncode == 0
    assert (first / "SHA256SUMS").read_text(encoding="utf-8") == (second / "SHA256SUMS").read_text(encoding="utf-8")


@pytest.mark.story("CAP-043", "AC7")
def test_dist_ac7_release_workflow():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for s in ('tags: ["v[0-9]+.[0-9]+.[0-9]+"]', "make check", "make dist", "sha256sum -c SHA256SUMS",
              "ubuntu-latest, macos-latest, windows-latest", "needs: install", "gh release create",
              "workflow_dispatch:", "if: github.event_name == 'push'      # a manual run is a dry run"):
        assert s in wf, s


@pytest.mark.story("CAP-043", "AC8")
def test_dist_ac8_single_build_path():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY dist/capellactl-*.whl" in docker and "python -m build" not in docker
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/build-dist.py" in ci and "python -m build" not in ci
    make = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "build: dist" in make and "image: dist" in make and "pip wheel" not in make
