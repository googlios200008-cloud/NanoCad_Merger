"""Small, stable integration surface for the Python host application Engi.

Core calls are synchronous and Qt-free. Run them in Engi's existing worker
thread, not on the GUI thread. ``open_window`` is optional and requires PySide6;
it never creates a second QApplication when one already exists.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .models import CancelEvent, MergeOptions, MergeResult, Progress


def merge_for_engi(
    input_folder: str | Path,
    output_folder: str | Path | None = None,
    *,
    oda_path: str | Path | None = None,
    options: MergeOptions | None = None,
    on_progress: Callable[[Progress], None] | None = None,
    cancel_event: CancelEvent | None = None,
) -> MergeResult:
    from .merger import merge_folder

    return merge_folder(
        input_folder,
        output_folder,
        oda_path=oda_path,
        options=options,
        progress=on_progress,
        cancel_event=cancel_event,
    )


def open_window(
    input_folder: str | Path | None = None,
    *,
    oda_path: str | Path | None = None,
    parent=None,
    on_finished: Callable[[MergeResult], None] | None = None,
):
    """Return a NanoMerger QMainWindow owned by the caller.

    Requires an existing PySide6 QApplication (or call ``run_app`` for standalone
    mode). Keep the returned object referenced by Engi. Connect to its signals
    through ``window.job_finished`` / ``window.job_failed`` if desired.
    """
    from .gui import NanoMergerWindow, require_qt

    require_qt()
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        raise RuntimeError(
            "В Engi должен быть создан QApplication, либо запустите nanomerger.gui.run_app()."
        )
    window = NanoMergerWindow(parent=parent, oda_path=oda_path)
    if input_folder:
        window.set_input_folder(input_folder)
    if on_finished:
        window.job_finished.connect(on_finished)
    window.show()
    return window
