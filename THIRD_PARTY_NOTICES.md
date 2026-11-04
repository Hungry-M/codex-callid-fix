# Third-party notices

This project is licensed under the MIT License (see `LICENSE`). Release
artifacts bundle or depend on third-party software with their own licenses.
This file is a summary, not legal advice; keep the full license texts with
distributed binaries.

## Bundled runtime

| Component | License | Notes |
| --- | --- | --- |
| Node.js (`runtime/node.exe`) | MIT and third-party licenses | The portable/installer payload includes the Node runtime. Include Node's `LICENSE` and third-party notices in the release. |
| PyInstaller bootloader | GPL-2.0-or-later with the PyInstaller bootloader exception | Used to produce the Windows EXEs. The exception permits distributing bundled applications under another license. |
| Python | PSF-2.0 | Python runtime embedded by PyInstaller. |
| Tcl/Tk | BSD-style | GUI toolkit embedded by PyInstaller. |
| sv-ttk | MIT | Tk/ttk theme used by the GUI. |

## Development-only

| Component | License |
| --- | --- |
| PyInstaller | GPL-2.0-or-later with bootloader exception |
| pytest (if used) | MIT |

## Release checklist

- [ ] Include the project `LICENSE`.
- [ ] Include this file.
- [ ] Include Node's `LICENSE` and third-party notices when bundling `node.exe`.
- [ ] Include PyInstaller/Python/Tk/sv-ttk license texts when distributing a frozen build.
- [ ] Do not add a dependency with an incompatible license without review.

Upstream license links:

- Node.js: <https://github.com/nodejs/node/blob/main/LICENSE>
- PyInstaller: <https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt>
- Python: <https://docs.python.org/3/license.html>
- Tcl/Tk: <https://www.tcl.tk/software/tcltk/license.html>
- sv-ttk: <https://github.com/rdbende/Sun-Valley-ttk-theme/blob/main/LICENSE>
