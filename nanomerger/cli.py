"""Command-line interface. No Qt import is required for batch automation."""

from __future__ import annotations

import argparse
import json
import sys
from importlib import metadata
from pathlib import Path

from . import __version__
from .converters import find_oda
from .discovery import scan_folder
from .errors import NanoMergerError
from .models import DWG_VERSIONS, MergeOptions, Progress


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nanomerger",
        description="NanoMerger — объединение нумерованных DWG из EPLAN в один комплект.",
    )
    parser.add_argument("--version", action="version", version=f"NanoMerger {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    merge = sub.add_parser(
        "merge", help="Объединить папку в DWG + многостраничный PDF + JSON-отчёт"
    )
    merge.add_argument("input", type=Path, help="Папка с исходными DWG (без рекурсии)")
    merge.add_argument(
        "-o", "--output", type=Path, help="Папка результата (по умолчанию INPUT/result)"
    )
    merge.add_argument("--name", help="Имя результата без расширения")
    merge.add_argument("--oda", type=Path, help="Путь к ODAFileConverter / ODAFileConverter.exe")
    merge.add_argument("--input-format", choices=("dwg", "dxf", "auto"), default="dwg")
    merge.add_argument(
        "--output-format",
        choices=("dwg", "dxf"),
        default="dwg",
        help="dxf — только явный DXF-режим без записи DWG",
    )
    merge.add_argument("--dwg-version", choices=tuple(DWG_VERSIONS), default="R2018")
    merge.add_argument(
        "--gap", type=float, default=50.0, help="Зазор между чертежами в мм (по умолчанию 50)"
    )
    merge.add_argument(
        "--columns", type=int, default=1, help="Столбцов в модели; 1 = одна горизонтальная лента"
    )
    merge.add_argument("--margin", type=float, default=10.0, help="Поля новых листов в мм")
    merge.add_argument(
        "--paper", choices=("auto", "source", "A4", "A3", "A2", "A1", "A0"), default="auto"
    )
    merge.add_argument(
        "--color-pdf", action="store_true", help="Сохранять цвета слоёв вместо чёрной геометрии"
    )
    merge.add_argument(
        "--timeout", type=float, default=1800.0, help="Таймаут одного запуска ODA, секунды"
    )
    merge.add_argument(
        "--overwrite", action="store_true", help="Разрешить замену существующего комплекта"
    )
    merge.add_argument(
        "--json", action="store_true", help="Итог JSON в stdout; ошибки JSON в stderr"
    )
    merge.add_argument("--quiet", action="store_true")
    merge.add_argument(
        "--debug", action="store_true", help="Показать traceback непредвиденной ошибки"
    )

    scan = sub.add_parser("scan", help="Проверить имена и показать порядок без чтения CAD")
    scan.add_argument("input", type=Path)
    scan.add_argument("--format", choices=("dwg", "dxf", "auto"), default="dwg")
    scan.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="Проверить Python-зависимости и наличие ODA")
    doctor.add_argument("--oda", type=Path)
    doctor.add_argument("--require-oda", action="store_true")
    doctor.add_argument("--json", action="store_true")

    gui = sub.add_parser("gui", help="Открыть настольное приложение")
    gui.add_argument("input", nargs="?", type=Path)
    gui.add_argument("--oda", type=Path)
    return parser


def _error(exc: Exception, as_json: bool) -> None:
    code = getattr(exc, "code", 1)
    if as_json:
        print(
            json.dumps(
                {
                    "error": type(exc).__name__,
                    "code": code,
                    "message": str(exc),
                    "details": getattr(exc, "details", ""),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
    else:
        print(f"Ошибка: {exc}", file=sys.stderr)
        if getattr(exc, "details", ""):
            print(exc.details, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = getattr(args, "json", False)
    try:
        if args.command == "scan":
            files, warnings = scan_folder(args.input, args.format)
            if as_json:
                print(
                    json.dumps(
                        {
                            "files": [
                                {
                                    "name": f.name,
                                    "path": str(f.path),
                                    "prefix": f.prefix,
                                    "number": f.number,
                                }
                                for f in files
                            ],
                            "warnings": warnings,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                for index, item in enumerate(files, 1):
                    print(
                        f"{index:4d}. {item.name}  [номер={item.number if item.number is not None else '—'}]"
                    )
                for warning in warnings:
                    print(f"Предупреждение: {warning}", file=sys.stderr)
            return 0
        if args.command == "doctor":
            packages = {}
            for name in ("ezdxf", "matplotlib", "Pillow", "PySide6"):
                try:
                    packages[name] = metadata.version(name)
                except metadata.PackageNotFoundError:
                    packages[name] = None
            import importlib

            imports = {}
            for module in ("ezdxf", "matplotlib.figure", "PIL.Image", "PySide6.QtWidgets"):
                try:
                    importlib.import_module(module)
                    imports[module] = None
                except Exception as exc:
                    imports[module] = str(exc)
            oda = find_oda(args.oda)
            data = {
                "app": __version__,
                "python": sys.version.split()[0],
                "packages": packages,
                "import_errors": imports,
                "oda_path": str(oda) if oda else None,
                "oda_note": "Найден исполняемый файл; работоспособность проверяется конвертацией контрольного DWG.",
            }
            core_ok = all(
                packages[name] and imports[module] is None
                for name, module in (
                    ("ezdxf", "ezdxf"),
                    ("matplotlib", "matplotlib.figure"),
                    ("Pillow", "PIL.Image"),
                )
            )
            if as_json:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print(f"NanoMerger {__version__} | Python {data['python']}")
                for name, version in packages.items():
                    print(
                        f"  {name}: {version or 'не установлен' + (' (необязательно для CLI)' if name == 'PySide6' else '')}"
                    )
                for module, error in imports.items():
                    if error:
                        optional = (
                            " (необязательно для CLI)" if module.startswith("PySide6") else ""
                        )
                        print(f"  Импорт {module}{optional}: {error}")
                print(f"  ODA: {oda or 'не найден — нужен для DWG'}")
            return 0 if core_ok and (oda or not args.require_oda) else 3
        if args.command == "gui":
            from .gui import run_app

            return run_app(args.input, args.oda)
        options = MergeOptions(
            input_format=args.input_format,
            output_format=args.output_format,
            dwg_version=args.dwg_version,
            gap_mm=args.gap,
            columns=args.columns,
            margin_mm=args.margin,
            paper=args.paper,
            color_pdf=args.color_pdf,
            overwrite=args.overwrite,
            timeout_seconds=args.timeout,
        )
        from .merger import merge_folder

        def on_progress(event: Progress) -> None:
            if not args.quiet and not as_json:
                print(f"[{event.stage}] {event.message}", file=sys.stderr)

        result = merge_folder(
            args.input,
            args.output,
            output_name=args.name,
            options=options,
            oda_path=args.oda,
            progress=on_progress,
        )
        if as_json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        elif not args.quiet:
            print(f"\nГотово за {result.duration_seconds:.1f} с")
            print(f"CAD: {result.cad_path}\nPDF: {result.pdf_path}\nОтчёт: {result.report_path}")
            for warning in result.warnings:
                print(f"Предупреждение: {warning}", file=sys.stderr)
        return 0
    except NanoMergerError as exc:
        _error(exc, as_json)
        return exc.code
    except KeyboardInterrupt:
        _error(NanoMergerError("Прервано пользователем."), as_json)
        return 4
    except Exception as exc:
        if getattr(args, "debug", False):
            raise
        _error(exc, as_json)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
