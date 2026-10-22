#!/usr/bin/env python3
"""Generate downloads/ and the README Download section for the standalone executables (CAP-045).

    python scripts/update-downloads.py --from DIR   # the release's five executables: writes downloads/manifest.json
    python scripts/update-downloads.py              # regenerate SHA256SUMS, README.md and the README block from it
    python scripts/update-downloads.py --check      # fail when any of them is stale or the manifest is incomplete

The executables themselves are attached to the GitHub Release, not kept in Git (about 150 MB per release).
downloads/ keeps what describes them: manifest.json (file, platform, size, SHA-256), SHA256SUMS and README.md, and
every link points to the release asset. Before the first release the manifest is absent and both READMEs say so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "downloads"
README = ROOT / "README.md"
REPO = "couchbaselabs/capellactl"
START, END = "<!-- downloads:start -->", "<!-- downloads:end -->"
# A tag builds X.Y.Z; a dry run of the release workflow builds X.Y.Z.devN+gSHA (scripts/version.py).
NAME = re.compile(r"^capellactl-(?P<version>\d+\.\d+\.\d+(?:\.dev\d+\+g[0-9a-f]+)?)"
                  r"-(?P<os>macos|linux|windows)-(?P<arch>arm64|x86_64)(?P<exe>\.exe)?$")
# (os, arch) → who it is for; the order of the tables. The same words as the file names (AC1, AC4).
PLATFORMS = {
    ("macos", "arm64"): "macOS 12+, Apple silicon (M1–M4)",
    ("macos", "x86_64"): "macOS 12+, Intel",
    ("linux", "x86_64"): "Linux x86-64, glibc 2.28+ (RHEL/Rocky 8+, Ubuntu 20.04+, Debian 10+)",
    ("linux", "arm64"): "Linux ARM64, glibc 2.28+ (AWS Graviton, Ampere)",
    ("windows", "x86_64"): "Windows 10/11 and Server 2019+, 64-bit",
}
KEPT = {"README.md", "SHA256SUMS", "manifest.json"}  # everything downloads/ may hold in Git
# The release asset with the executables' checksums; the release's SHA256SUMS covers the wheel and source archive.
ASSET_SUMS = "SHA256SUMS-executables"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_from(directory: Path) -> dict[str, Any]:
    files = []
    for p in sorted(directory.iterdir()):
        m = NAME.match(p.name)
        if m:
            files.append({"file": p.name, "os": m["os"], "arch": m["arch"], "size": p.stat().st_size,
                          "sha256": sha256(p)})
    versions = {NAME.match(f["file"])["version"] for f in files}  # type: ignore[index]
    if len(versions) != 1:
        raise SystemExit(f"update-downloads: expected one version in {directory}, found {sorted(versions) or 'none'}")
    return {"version": versions.pop(), "files": files}


def problems(manifest: dict[str, Any] | None, present: set[str]) -> list[str]:
    """What is wrong with downloads/ (AC3): five platforms, one version, checksums, nothing else kept."""
    out = [f"downloads/{n} should not be in Git (only {', '.join(sorted(KEPT))})" for n in sorted(present - KEPT)]
    if manifest is None:
        return out
    seen = set()
    for f in manifest["files"]:
        m = NAME.match(f["file"])
        if m is None:
            out.append(f"{f['file']}: not a capellactl-<version>-<os>-<arch> name")
            continue
        if m["version"] != manifest["version"]:
            out.append(f"{f['file']}: version {m['version']}, the release is {manifest['version']}")
        if (m["os"], m["arch"]) != (f["os"], f["arch"]):
            out.append(f"{f['file']}: listed as {f['os']}-{f['arch']}")
        if bool(m["exe"]) != (m["os"] == "windows"):
            out.append(f"{f['file']}: only the Windows file ends in .exe")
        if not re.fullmatch(r"[0-9a-f]{64}", str(f.get("sha256", ""))):
            out.append(f"{f['file']}: no SHA-256")
        seen.add((m["os"], m["arch"]))
    for missing in PLATFORMS.keys() - seen:
        out.append(f"no executable for {'-'.join(missing)}")
    if len(manifest["files"]) != len(seen):
        out.append("more than one executable for a platform")
    return out


def _url(version: str, file: str) -> str:
    return f"https://github.com/{REPO}/releases/download/v{version}/{file}"


def _ordered(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    order = list(PLATFORMS)
    return sorted(manifest["files"], key=lambda f: order.index((f["os"], f["arch"])) if (f["os"], f["arch"]) in
                  order else len(order))


def sums(manifest: dict[str, Any] | None) -> str | None:
    if manifest is None:
        return None
    return "".join(f"{f['sha256']}  {f['file']}\n" for f in _ordered(manifest))


def table(manifest: dict[str, Any] | None) -> str:
    if manifest is None:
        rows = [f"| {who} | `capellactl-<version>-{o}-{a}{'.exe' if o == 'windows' else ''}` | | |"
                for (o, a), who in PLATFORMS.items()]
        note = ("**Not released yet**: these files are attached to each "
                f"[GitHub Release](https://github.com/{REPO}/releases) from 1.0.0 on. Until then, install from "
                "source.")
        return "\n".join([note, "", "| Your computer | File | Size | SHA-256 |", "|---|---|---|---|", *rows])
    else:
        v = manifest["version"]
        rows = [f"| {PLATFORMS.get((f['os'], f['arch']), f['os'] + ' ' + f['arch'])} | [{f['file']}]({_url(v, f['file'])}) "
                f"| {f['size'] / 1_000_000:.0f} MB | `{f['sha256'][:12]}…` |" for f in _ordered(manifest)]
        note = (f"Release {v}. Full checksums: [SHA256SUMS-executables]({_url(v, ASSET_SUMS)}) "
                "(the same as [downloads/SHA256SUMS](downloads/SHA256SUMS)).")
    return "\n".join(["| Your computer | File | Size | SHA-256 |", "|---|---|---|---|", *rows, "", note])


HOW_TO = """\
Which one? On macOS, Apple menu → About This Mac: *Chip: Apple M…* is Apple silicon, *Processor: Intel* is Intel.
On Linux, `uname -m`: `aarch64` is ARM64, `x86_64` is x86-64.

Run it:

```bash
# macOS and Linux (example: Linux x86-64)
shasum -a 256 -c SHA256SUMS-executables --ignore-missing   # Linux: sha256sum -c …
chmod +x capellactl-*-linux-x86_64
./capellactl-*-linux-x86_64 --version          # optional: move it to /usr/local/bin/capellactl
```

```powershell
# Windows, in PowerShell: compare the hash with the line in SHA256SUMS-executables, then run it
(Get-FileHash .\\capellactl-*-windows-x86_64.exe -Algorithm SHA256).Hash
.\\capellactl-*-windows-x86_64.exe --version
```

The executables are not code-signed, so check the SHA-256 first (above), then allow the file once:

- **macOS**: a file downloaded in a browser is blocked as from an unidentified developer. Remove the download mark
  with `xattr -d com.apple.quarantine ./capellactl-*-macos-*`, or run it once and choose *Allow Anyway* in
  System Settings → Privacy & Security. Files fetched with `curl` are not marked.
- **Windows**: run `Unblock-File .\\capellactl-*-windows-x86_64.exe` in PowerShell, or choose *More info → Run anyway*
  when SmartScreen warns. Company policy (AppLocker, WDAC) may need IT to allow the file's hash.
- **Linux**: nothing more than `chmod +x`.

Each executable carries `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md` and `BINARY_NOTICES.md`; the same files are
attached to the release next to it."""


def downloads_readme(manifest: dict[str, Any] | None) -> str:
    return ("# capellactl standalone executables\n\n"
            "> Generated by `scripts/update-downloads.py` from `manifest.json`. Don't edit by hand.\n\n"
            "One file per computer: no Python, pip or Docker needed (CAP-045).\n\n"
            + table(manifest).replace("](downloads/SHA256SUMS)", "](SHA256SUMS)") + "\n\n" + HOW_TO + "\n")


def readme_block(manifest: dict[str, Any] | None) -> str:
    return (f"{START}\n{table(manifest)}\n\nHow to pick, verify and run the right file: "
            f"[downloads/README.md](downloads/README.md).\n{END}")


def expected(manifest: dict[str, Any] | None, readme: str) -> dict[Path, str | None]:
    if START not in readme or END not in readme:
        raise SystemExit(f"update-downloads: README.md has no {START} … {END} block")
    head, rest = readme.split(START, 1)
    return {DOWNLOADS / "SHA256SUMS": sums(manifest), DOWNLOADS / "README.md": downloads_readme(manifest),
            README: head + readme_block(manifest) + rest.split(END, 1)[1]}


def load_manifest() -> dict[str, Any] | None:
    p = DOWNLOADS / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="source", type=Path, help="directory holding the release's executables")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.source:
        DOWNLOADS.mkdir(exist_ok=True)
        (DOWNLOADS / "manifest.json").write_text(json.dumps(manifest_from(a.source), indent=2) + "\n",
                                                 encoding="utf-8")
    manifest = load_manifest()
    present = {p.name for p in DOWNLOADS.iterdir()} if DOWNLOADS.is_dir() else set()
    issues = problems(manifest, present)
    want = expected(manifest, README.read_text(encoding="utf-8"))
    if a.check:
        for path, text in want.items():
            have = path.read_text(encoding="utf-8") if path.exists() else None
            if have != text:
                issues.append(f"{path.relative_to(ROOT)} is stale; run: python scripts/update-downloads.py")
        for i in issues:
            print(f"update-downloads: {i}", file=sys.stderr)
        if issues:
            return 1
        print("downloads/ and the README Download section are up to date")
        return 0
    if issues:
        for i in issues:
            print(f"update-downloads: {i}", file=sys.stderr)
        return 1
    DOWNLOADS.mkdir(exist_ok=True)
    for path, text in want.items():
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text, encoding="utf-8")
    print("downloads/ and the README Download section updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
