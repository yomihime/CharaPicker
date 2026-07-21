# Third-Party Notices

This document summarizes the main third-party components used by CharaPicker.
It is provided for attribution and release packaging convenience. The license
texts and notices published by each upstream project control.

CharaPicker's own source code is licensed under the Mozilla Public License 2.0
(`MPL-2.0`). See `LICENSE`.

## Binary Distribution Note

The Windows release package is produced with PyInstaller and may bundle Python
packages, Qt runtime files, and other third-party components from the build
environment. CharaPicker's `MPL-2.0` license does not replace or narrow the
licenses of those third-party components.

Current open-source builds use GPL-licensed Python UI dependencies. When a
binary release includes GPL-licensed builds of PyQt6 or PyQt6-Fluent-Widgets,
the distributor must comply with the applicable GPL terms for that distribution
in addition to the MPL-2.0 terms for CharaPicker's own source files. If a future
release uses commercial or alternative licenses for those components, this file
should be updated before publishing.

## Direct Runtime Dependencies

| Component | Use | License noted by upstream | Upstream |
| --- | --- | --- | --- |
| PyQt6 | Python bindings for Qt 6 UI | GPL-3.0 or Riverbank Commercial License | https://www.riverbankcomputing.com/software/pyqt/ |
| Qt 6 runtime files | Qt application framework runtime included through PyQt6 wheels/builds | Qt licensing varies by module and distribution; PyQt6 GPL wheels include corresponding Qt runtime files | https://www.qt.io/licensing/ |
| PyQt6-Fluent-Widgets / qfluentwidgets | Fluent UI widgets | GPL-3.0 for the Python package unless another upstream license is obtained | https://github.com/zhiyiYo/PyQt-Fluent-Widgets |
| pydantic | Data validation and models | MIT | https://github.com/pydantic/pydantic |
| pypdf | Text extraction and metadata inspection for PDF inputs | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| requests | HTTP client | Apache-2.0 | https://github.com/psf/requests |
| dashscope | Alibaba Cloud DashScope SDK | Apache-2.0 | https://github.com/dashscope/dashscope-sdk-python |
| PySocks | SOCKS proxy support for requests | BSD-style license | https://github.com/Anorov/PySocks |

## Build And Packaging Tools

| Component | Use | License noted by upstream | Upstream |
| --- | --- | --- | --- |
| PyInstaller | Windows one-folder packaging | GPL-2.0-or-later with PyInstaller bootloader exception | https://www.pyinstaller.org/ |

## Optional External Runtime Tools

| Component | Use | License noted by upstream | Upstream |
| --- | --- | --- | --- |
| 7-Zip | Optional local backend for listing, testing, and extracting 7z/RAR-family project inputs | GNU LGPL for the executable; 7z.dll also includes LGPL code with the unRAR restriction and BSD-licensed code | https://www.7-zip.org/ |

CharaPicker discovers a user-installed or project-local 7-Zip runtime and does
not download it. If a release package bundles 7-Zip, it must also reproduce the
license information shipped by that 7-Zip version and satisfy its applicable
redistribution terms.

## Runtime Assets

| Asset | Use | Notice |
| --- | --- | --- |
| `res/app_icon.*` | Application icon | AI-generated draft manually edited by the project maintainer; see `docs/reference/asset-material-declaration.zh_CN.md`. |
| `res/test_media/*` | Model test media | Image/video files are network-sourced free test materials; audio is maintainer-recorded. See `docs/reference/asset-material-declaration.zh_CN.md`. |

## Release Checklist

- Include `LICENSE` and `THIRD_PARTY_NOTICES.md` in every release zip.
- Re-check the licenses of bundled dependencies when upgrading PyQt6,
  PyQt6-Fluent-Widgets, Qt, PyInstaller, or any runtime package.
- When bundling 7-Zip, include its version-matched `License.txt` and re-check
  the LGPL, unRAR restriction, and bundled codec notices.
- For binary distribution with GPL components, make corresponding source and
  license information available in a way that satisfies the applicable GPL
  obligations.
- For public binary releases, prefer publishing from a Git tag so the matching
  source code is easy to find.
