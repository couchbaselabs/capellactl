# PyInstaller build of the standalone executable (CAP-045). Run through `make binary` / scripts/build-binary.py,
# which names the result capellactl-<version>-<os>-<arch>[.exe]. One file, console app, no Python needed.
# -*- mode: python -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

ROOT = Path(SPECPATH)  # noqa: F821 - defined by PyInstaller

# Read at run time from inside the package: the config schema, the init presets, the known node sizes and the help pages.
datas = [(str(ROOT / "capellactl" / "config" / "schema.json"), "capellactl/config"),
         (str(ROOT / "capellactl" / "config" / "presets.yaml"), "capellactl/config"),
         (str(ROOT / "capellactl" / "config" / "compute.yaml"), "capellactl/config")]
datas += [(str(p), "capellactl/help") for p in sorted((ROOT / "capellactl" / "help").glob("*.md"))]
# Licence and notices, inside the executable as well as next to it in the release (CAP-044, AC7).
datas += [(str(ROOT / name), ".") for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "BINARY_NOTICES.md")]
# capellactl.__version__ and keyring's backend discovery read installed-package metadata.
datas += copy_metadata("capellactl") + copy_metadata("keyring")
datas += collect_data_files("jsonschema_specifications")

a = Analysis(  # noqa: F821
    [str(ROOT / "capellactl" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=datas,
    # imported by name at run time, so the analysis can't see them
    hiddenimports=["keyring.backends.macOS", "keyring.backends.Windows", "keyring.backends.SecretService",
                   "keyring.backends.fail", "keyring.backends.null", "keyring.backends.chainer"],
    excludes=["tkinter", "unittest", "pydoc_data", "test"],
    noarchive=False,
)
# An editable install's direct_url.json holds the path of the build machine's checkout: never ship it (AC7).
# copy_metadata adds whole .dist-info folders, so it is dropped from the analysed file list.
a.datas = [entry for entry in a.datas if Path(entry[0]).name != "direct_url.json"]
pyz = PYZ(a.pure)  # noqa: F821
# macOS release builds (AC6): PyInstaller signs every bundled library and the executable with the Developer ID
# identity, with the hardened runtime. A one-file build unpacks the libraries at start, so the executable needs the
# entitlement that lets it load them. Unset (every other build): nothing is signed.
identity = os.environ.get("CAPELLACTL_CODESIGN_IDENTITY") or None
exe = EXE(  # noqa: F821
    pyz, a.scripts, a.binaries, a.datas, [],
    name="capellactl",
    console=True,
    strip=False,
    upx=False,
    codesign_identity=identity,
    entitlements_file=str(ROOT / "packaging" / "entitlements.plist") if identity else None,
)
