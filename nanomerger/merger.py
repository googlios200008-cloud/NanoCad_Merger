"""Synchronous, Qt-free orchestration suitable for Engi worker threads and CLI."""

from __future__ import annotations

import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import ezdxf

from . import __version__
from .converters import DrawingConverter, DxfPassthroughConverter, OdaConverter, check_cancel
from .discovery import scan_folder
from .drawing import build_document, prepare_source
from .errors import ConversionError
from .models import CancelEvent, MergeOptions, MergeResult, Progress, ProgressCallback
from .publishing import check_existing, output_paths, publish, sha256


def merge_folder(
    input_dir: str | Path,
    output_dir: str | Path | None = None,
    *,
    output_name: str | None = None,
    options: MergeOptions | None = None,
    converter: DrawingConverter | None = None,
    oda_path: str | Path | None = None,
    progress: ProgressCallback | None = None,
    cancel_event: CancelEvent | None = None,
) -> MergeResult:
    """Merge numbered drawings from one non-recursive folder.

    Default pipeline: DWG → temporary DXF → resource-isolated blocks → model
    placements + one layout per source → real DWG via ODA → read saved DWG back
    → multipage PDF → report → publish complete result.

    The caller owns ``cancel_event``. Progress callbacks run on the calling
    thread; Engi/Qt adapters must marshal them to the GUI thread via signals.
    No global matplotlib backend or Qt application is changed by this function.
    """
    started = time.monotonic()
    options = options or MergeOptions()
    folder = Path(input_dir).expanduser().resolve()
    sources, warnings = scan_folder(folder, options.input_format)
    paths = output_paths(
        folder, Path(output_dir) if output_dir is not None else None, output_name, sources, options
    )
    check_existing(paths, options.overwrite)
    destination = paths["cad"].parent
    if destination == folder:
        warnings.append(
            "Результат сохраняется в исходную папку. При следующем запуске выберите отдельную папку результата, чтобы не объединять предыдущий итог."
        )
    if converter is None:
        converter = (
            DxfPassthroughConverter()
            if options.output_format == "dxf"
            else OdaConverter(oda_path, timeout_seconds=options.timeout_seconds)
        )
    elif oda_path is not None:
        from .errors import InputError

        raise InputError("Передайте либо готовый converter, либо oda_path, но не оба параметра.")

    def emit(stage: str, completed: int, total: int, message: str) -> None:
        check_cancel(cancel_event)
        if progress:
            progress(Progress(stage, completed, total, message))

    emit("scan", 1, 1, f"Найдено файлов: {len(sources)}")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".nanomerger-job-", dir=destination) as tmp:
        work = Path(tmp)
        check_cancel(cancel_event)
        converted = converter.read_drawings(
            [item.path for item in sources], work / "input-dxf", cancel=cancel_event
        )
        emit("convert", len(sources), len(sources), "Исходные чертежи прочитаны конвертером")
        prepared = []
        source_hashes: dict[str, str] = {}
        for index, item in enumerate(sources, start=1):
            check_cancel(cancel_event)
            if item.path not in converted:
                raise ConversionError(f"Конвертер не вернул DXF для {item.name}.")
            prepared.append(prepare_source(item, converted[item.path], options))
            warnings.extend(prepared[-1].warnings)
            source_hashes[item.name] = sha256(item.path)
            emit("prepare", index, len(sources), f"Подготовлен {item.name}")
        document, sheets = build_document(prepared, options)
        emit("build", len(sheets), len(sheets), f"Создана модель и листов: {len(sheets)}")
        merged_dxf = work / f"{paths['cad'].stem}.dxf"
        document.saveas(merged_dxf)
        staged_cad = work / paths["cad"].name
        if options.output_format == "dwg":
            emit("cad", 0, 1, "Запись настоящего DWG через ODA…")
            converter.write_dwg(merged_dxf, staged_cad, options.dwg_version, cancel=cancel_event)
            # PDF is based on the actual delivered DWG, not merely the in-memory
            # pre-conversion document. This catches converter-side layout loss.
            roundtrip = converter.read_drawings(
                [staged_cad], work / "roundtrip-dxf", cancel=cancel_event
            )
            final_document = ezdxf.readfile(roundtrip[staged_cad])
            emit("cad", 1, 1, f"DWG {options.dwg_version} записан и прочитан обратно")
        else:
            staged_cad = merged_dxf
            final_document = ezdxf.readfile(merged_dxf)
            emit("cad", 1, 1, "Записан DXF (явный режим без DWG)")
        check_cancel(cancel_event)
        from .pdf import render_pdf

        staged_pdf = work / paths["pdf"].name
        render_pdf(
            final_document, sheets, staged_pdf, options, cancel=cancel_event, progress=progress
        )
        warnings.append(
            "PDF — векторная визуализация сохранённого CAD-файла через ezdxf/matplotlib, не native-печать CAD: CTB/STB, драйверы принтеров и замена SHX-шрифтов могут отличаться."
        )
        if options.output_format == "dwg":
            warnings.append(
                "DWG проходит преобразование ODA DWG→DXF→DWG. Проверьте итог в CAD на контрольном комплекте EPLAN перед выдачей заказчику."
            )
        duration = time.monotonic() - started
        report = {
            "schema": "nanomerger.report/1",
            "app_version": __version__,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "input_dir": str(folder),
            "options": asdict(options),
            "sources": [
                {
                    "name": item.name,
                    "prefix": item.prefix,
                    "number": item.number,
                    "sha256": source_hashes[item.name],
                }
                for item in sources
            ],
            "sheets": [asdict(sheet) for sheet in sheets],
            "outputs": {
                "cad": paths["cad"].name,
                "pdf": paths["pdf"].name,
                "cad_sha256": sha256(staged_cad),
                "pdf_sha256": sha256(staged_pdf),
            },
            "pdf_engine": "ezdxf + matplotlib (vector preview; not a CAD plot)",
            "warnings": list(dict.fromkeys(warnings)),
            "duration_seconds": round(duration, 3),
            "status": "complete",
        }
        import json

        staged_report = work / paths["report"].name
        staged_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        check_cancel(cancel_event)
        emit("publish", 0, 1, "Публикация полного комплекта результатов…")
        publish(
            {paths["cad"]: staged_cad, paths["pdf"]: staged_pdf, paths["report"]: staged_report},
            overwrite=options.overwrite,
        )
    result = MergeResult(
        output_dir=destination,
        cad_path=paths["cad"],
        pdf_path=paths["pdf"],
        report_path=paths["report"],
        dwg_path=paths["cad"] if options.output_format == "dwg" else None,
        dxf_path=paths["cad"] if options.output_format == "dxf" else None,
        sheets=sheets,
        warnings=tuple(dict.fromkeys(warnings)),
        duration_seconds=round(duration, 3),
    )
    if progress:
        progress(
            Progress("done", 1, 1, f"Готово: {len(sheets)} листов, {result.duration_seconds:.1f} с")
        )
    return result
