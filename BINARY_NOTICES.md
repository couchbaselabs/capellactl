# Notices for the standalone executables

The standalone executables of capellactl (`capellactl-<version>-<os>-<arch>`, CAP-045) contain, besides
capellactl and the dependencies listed in `THIRD_PARTY_NOTICES.md`:

| Component | Licence | Why it is included |
|---|---|---|
| [CPython](https://www.python.org/) interpreter and standard library | PSF-2.0 | Runs capellactl, so no Python needs to be installed |
| [PyInstaller](https://pyinstaller.org/) bootloader | GPL-2.0-or-later with the PyInstaller bootloader exception | Starts the bundled interpreter |

The bootloader exception allows the bootloader to be distributed in executables under any licence, so it does not
change the licence of capellactl (Apache-2.0, see `LICENSE`). The full texts are at
<https://docs.python.org/3/license.html> and <https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt>.

The wheel and the source archive (CAP-043) contain neither.
