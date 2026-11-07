"""Minimal Engi-side example. Adapt the worker base class to Engi's framework.

Core-only usage does not import Qt. If Engi already uses PySide6, the optional
window can be opened with nanomerger.engi.open_window(parent=engi_main_window).
If Engi uses another GUI framework, call merge_for_engi in its worker thread or
launch the CLI as a subprocess and consume --json output.
"""

from __future__ import annotations

from pathlib import Path

from nanomerger import MergeOptions
from nanomerger.engi import merge_for_engi


def run_batch(input_folder: str | Path, output_folder: str | Path, oda_path: str) -> None:
    def on_progress(event) -> None:
        # Marshal to Engi's UI thread here if this runs in a worker.
        print(event.stage, event.message)

    result = merge_for_engi(
        input_folder,
        output_folder,
        oda_path=oda_path,
        options=MergeOptions(gap_mm=50, columns=0, paper="auto", dwg_version="R2018"),
        on_progress=on_progress,
    )
    print(result.dwg_path, result.pdf_path, result.report_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--oda", required=True)
    args = parser.parse_args()
    run_batch(args.input, args.output, args.oda)
