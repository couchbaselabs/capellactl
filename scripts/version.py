"""The package version, single-sourced from git tags (CAP-043 AC5). Hatchling calls get_version() at build time.

- HEAD tagged vX.Y.Z           → X.Y.Z
- untagged, after tag vX.Y.Z   → X.Y.(Z+1).devN+gSHA   (N commits since the tag)
- untagged, no release tag yet → NEXT_RELEASE.devN+gSHA (N commits in total)
- no git (a source archive)    → the Version recorded in its PKG-INFO
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

NEXT_RELEASE = "1.0.0"  # the release being prepared before its tag exists
ROOT = Path(__file__).resolve().parents[1]
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10, encoding="utf-8")
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def get_version() -> str:
    pkg_info = ROOT / "PKG-INFO"
    if pkg_info.exists():
        for line in pkg_info.read_text(encoding="utf-8").splitlines():
            if line.startswith("Version: "):
                return line.split(": ", 1)[1].strip()
    sha = _git("rev-parse", "--short=7", "HEAD")
    if sha is None:
        return f"{NEXT_RELEASE}.dev0"
    exact = _git("describe", "--tags", "--exact-match", "--match", "v[0-9]*", "HEAD")
    if exact and TAG.match(exact):
        return exact[1:]
    last = _git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "HEAD")
    m = TAG.match(last or "")
    if m:
        base = f"{m[1]}.{m[2]}.{int(m[3]) + 1}"
        count = _git("rev-list", "--count", f"{last}..HEAD") or "0"
    else:
        base = NEXT_RELEASE
        count = _git("rev-list", "--count", "HEAD") or "0"
    return f"{base}.dev{count}+g{sha}"


def release_tag() -> str | None:
    """vX.Y.Z when HEAD carries a release tag."""
    exact = _git("describe", "--tags", "--exact-match", "--match", "v[0-9]*", "HEAD")
    return exact if exact and TAG.match(exact) else None


def source_date_epoch() -> str:
    """Commit time of HEAD, so two builds of the same commit produce identical archives (AC6)."""
    return _git("log", "-1", "--format=%ct", "HEAD") or "315532800"


if __name__ == "__main__":
    print(get_version())
