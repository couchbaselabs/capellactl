#!/usr/bin/env python3
"""Build the distributables: source archive, wheel and SHA256SUMS (CAP-043). `make dist` runs this.

Usage: python scripts/build-dist.py [--outdir dist]

The archives are versioned from the git tag (scripts/version.py) and reproducible: SOURCE_DATE_EPOCH is the commit
time. The build fails when an archive holds a file outside the allowlist, when `twine check` fails, or, on a
release tag, when CHANGELOG.md has no section for the version.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import version as version_mod  # noqa: E402

# Top-level entries a source archive may contain (pyproject's sdist only-include, plus what the build adds).
SDIST_TOP = {"capellactl", "tests", "docs", "scripts", "README.md", "CONTRIBUTING.md", "CHANGELOG.md", "LICENSE",
             "NOTICE", "THIRD_PARTY_NOTICES.md", "pyproject.toml", "Makefile", "Dockerfile", "PKG-INFO",
             ".gitignore"}  # hatchling keeps .gitignore so a wheel built from the archive excludes the same files
# Never in any archive, wherever they are: local environment files, credentials and assistant files.
FORBIDDEN = ["capella.yaml", "capella.yml", "capella.yaml.*", "capella.yml.*", "*.bak", ".capellactl", ".env",
             "secrets", "CLAUDE.md", "CLAUDE.local.md", ".claude", ".mcp.json", "*.swp", "__pycache__", "*.pyc"]
# Allowed despite FORBIDDEN: the documented example files and test fixtures.
ALLOWED = ["docs/release-*/examples/*", "tests/scenario/fixtures/*", "docs/examples/*"]


class BuildError(Exception):
    pass


def changelog_has(ver: str) -> bool:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8") if (ROOT / "CHANGELOG.md").exists() else ""
    return any(line.strip().startswith(f"## {ver}") or line.strip().startswith(f"## [{ver}]")
               for line in text.splitlines())


def _forbidden(rel: str) -> str | None:
    if any(fnmatch.fnmatch(rel, a) for a in ALLOWED):
        return None
    for part in rel.split("/"):
        for pat in FORBIDDEN:
            if fnmatch.fnmatch(part, pat):
                return pat
    return None


def check_sdist(path: Path) -> list[str]:
    problems = []
    with tarfile.open(path) as tf:
        names = [m.name for m in tf.getmembers() if m.isfile()]
    prefix = names[0].split("/", 1)[0] + "/"
    for n in names:
        rel = n[len(prefix):] if n.startswith(prefix) else n
        if rel.split("/", 1)[0] not in SDIST_TOP:
            problems.append(f"{path.name}: {rel} is not in the source-archive allowlist")
        elif _forbidden(rel):
            problems.append(f"{path.name}: {rel} must never ship")
    for needed in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "capellactl/config/schema.json"):
        if prefix + needed not in names:
            problems.append(f"{path.name}: {needed} is missing")
    return problems


def check_wheel(path: Path) -> list[str]:
    problems = []
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    for n in names:
        top = n.split("/", 1)[0]
        if top != "capellactl" and not (top.startswith("capellactl-") and top.endswith(".dist-info")):
            problems.append(f"{path.name}: {n} is not in the wheel allowlist")
        elif _forbidden(n):
            problems.append(f"{path.name}: {n} must never ship")
    for needed in ("licenses/LICENSE", "licenses/NOTICE"):
        if not any(n.endswith(".dist-info/" + needed) for n in names):
            problems.append(f"{path.name}: {needed} is missing")
    for needed in ("capellactl/config/schema.json", "capellactl/config/presets.yaml", "capellactl/help/ci.md"):
        if needed not in names:
            problems.append(f"{path.name}: {needed} is missing")
    return problems


def sha256sums(files: list[Path]) -> str:
    return "".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n" for f in sorted(files))


def build(outdir: Path) -> list[Path]:
    ver = version_mod.get_version()
    tag = version_mod.release_tag()
    if tag and not changelog_has(ver):
        raise BuildError(f"CHANGELOG.md has no '## {ver}' section; add one before releasing {tag}")
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    env = {**os.environ, "SOURCE_DATE_EPOCH": version_mod.source_date_epoch()}
    # sdist first, then the wheel built from the sdist: proves the source archive is complete (AC2).
    r = subprocess.run([sys.executable, "-m", "build", "--no-isolation", "--outdir", str(outdir), str(ROOT)],
                       env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise BuildError("build failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])
    sdists, wheels = sorted(outdir.glob("*.tar.gz")), sorted(outdir.glob("*.whl"))
    if len(sdists) != 1 or len(wheels) != 1:
        raise BuildError(f"expected one source archive and one wheel in {outdir}, found "
                         f"{', '.join(p.name for p in outdir.iterdir())}")
    problems = check_sdist(sdists[0]) + check_wheel(wheels[0])
    if problems:
        raise BuildError("archive check failed:\n  " + "\n  ".join(problems))
    r = subprocess.run([sys.executable, "-m", "twine", "check", "--strict", str(sdists[0]), str(wheels[0])],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise BuildError("twine check failed:\n" + r.stdout + r.stderr)
    files = [sdists[0], wheels[0]]
    (outdir / "SHA256SUMS").write_text(sha256sums(files), encoding="utf-8")
    return [*files, outdir / "SHA256SUMS"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--outdir", default=str(ROOT / "dist"))
    args = ap.parse_args()
    try:
        files = build(Path(args.outdir).resolve())
    except BuildError as exc:
        print(f"make dist: {exc}", file=sys.stderr)
        return 1
    print(f"capellactl {version_mod.get_version()}:")
    for f in files:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
