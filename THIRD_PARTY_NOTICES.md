# Third-party components

NanoMerger itself is MIT-licensed. Runtime dependencies are installed separately
by pip and retain their own licenses:

| Component | Role | License / distribution note |
|---|---|---|
| ezdxf 1.4.3 | DXF parsing, entities, layouts, rendering frontend | MIT |
| matplotlib | Vector PDF backend | PSF-based matplotlib license |
| Pillow | Image support required by the ezdxf drawing frontend | MIT-CMU |
| PySide6 (optional GUI) | Desktop shell and Engi window integration | LGPLv3 or commercial Qt license; review obligations when bundling an EXE |
| ODA File Converter | External DWG/DXF conversion executable | Proprietary ODA terms; user installs separately, not bundled or downloaded by NanoMerger |
| pypdf (dev/tests only) | PDF assertions in tests | BSD |

PyMuPDF is **not** a runtime dependency of NanoMerger. The PDF pipeline uses
matplotlib to avoid adding an AGPL runtime dependency to the application.

When distributing a frozen Windows build, include the license texts required by
the bundled Python packages and review Qt/LGPL obligations. ODA must remain a
separately installed component unless you have a separate distribution license.
