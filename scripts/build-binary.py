#!/usr/bin/env python3
"""Build the standalone executable for this machine (CAP-045). `make binary` runs this.

Usage: python scripts/build-binary.py [--outdir dist/binary] [--no-smoke]

Builds capellactl.spec with PyInstaller (one file, nothing else needed to run it), names the result
capellactl-<version>-<os>-<arch>[.exe], puts it in --outdir next to LICENSE, NOTICE, THIRD_PARTY_NOTICES.md and
BINARY_NOTICES.md, and runs the smoke tests (tests/binary) on it. An executable can only be built on its own
platform; the release workflow builds all five. Needs `pip install -e ".[binary]"`.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import version as version_mod  # noqa: E402

OS_NAMES = {"darwin": "macos", "linux": "linux", "windows": "windows"}
ARCH_NAMES = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64", "x64": "x86_64"}
NOTICES = ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "BINARY_NOTICES.md")


class BuildError(Exception):
    pass


def binary_name(version: str, system: str, machine: str) -> str:
    """capellactl-1.0.0-linux-arm64, from platform.system() and platform.machine() (AC1)."""
    os_name, arch = OS_NAMES.get(system.lower()), ARCH_NAMES.get(machine.lower())
    if os_name is None or arch is None:
        raise BuildError(f"no standalone executable for {system} {machine}; supported: macOS, Linux and Windows "
                         "on x86-64 and ARM64")
    return f"capellactl-{version}-{os_name}-{arch}" + (".exe" if os_name == "windows" else "")


def build(outdir: Path, work: Path) -> Path:
    version = version_mod.get_version()
    installed = metadata.version("capellactl")
    if installed != version:  # the executable reports the installed metadata's version
        raise BuildError(f"the installed capellactl is {installed}, the source is {version}; "
                         "run: pip install -e \".[binary]\" and build again")
    name = binary_name(version, platform.system(), platform.machine())
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
                        "--distpath", str(work / "dist"), "--workpath", str(work / "build"), str(ROOT / "capellactl.spec")],
                       cwd=ROOT)
    if r.returncode != 0:
        raise BuildError("PyInstaller failed")
    built = work / "dist" / ("capellactl.exe" if name.endswith(".exe") else "capellactl")
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("capellactl-*"):  # exactly one executable for this platform (AC1)
        old.unlink()
    target = outdir / name
    shutil.move(str(built), target)
    for n in NOTICES:
        shutil.copy2(ROOT / n, outdir / n)
    return target


def smoke(binary: Path) -> int:
    env = {**os.environ, "CAPELLACTL_BINARY": str(binary), "CAPELLACTL_BINARY_VERSION": version_mod.get_version()}
    return subprocess.run([sys.executable, "-m", "pytest", "-m", "binary", "-p", "no:cacheprovider", "-q",
                           str(ROOT / "tests" / "binary")], cwd=ROOT, env=env).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--outdir", type=Path, default=ROOT / "dist" / "binary")
    ap.add_argument("--no-smoke", action="store_true", help="skip the smoke tests")
    a = ap.parse_args(argv)
    try:
        binary = build(a.outdir.resolve(), ROOT / "build" / "binary")
    except BuildError as exc:
        print(f"build-binary: {exc}", file=sys.stderr)
        return 1
    size = binary.stat().st_size / 1_000_000
    print(f"{binary} ({size:.1f} MB)")
    return 0 if a.no_smoke else smoke(binary)


if __name__ == "__main__":
    sys.exit(main())
