"""Точка входа для PyInstaller и python -m nanomerger.desktop_entry.

В оконном EXE stderr не виден, поэтому фатальные ошибки старта показываются
системным диалогом Windows и пишутся во временный журнал.
"""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path


def _show_fatal(message: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "NanoMerger — ошибка запуска", 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def main() -> int:
    log_path: Path | None = None
    try:
        from nanomerger.gui import main as gui_main
        from nanomerger.gui import require_qt

        require_qt()
        return gui_main()
    except Exception as exc:
        detail = traceback.format_exc()
        try:
            log_path = Path(tempfile.gettempdir()) / "NanoMerger-startup.log"
            log_path.write_text(detail, encoding="utf-8")
        except OSError:
            log_path = None
        location = f"\nЖурнал: {log_path}" if log_path else ""
        _show_fatal(f"Не удалось запустить NanoMerger.\n\n{exc}{location}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
