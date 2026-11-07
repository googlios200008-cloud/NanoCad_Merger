#!/usr/bin/env python3
"""Сборка NanoMerger.exe на Windows — можно запускать прямо из PyCharm.

Быстрый старт:
    1. Откройте корень репозитория в PyCharm на Windows.
    2. Откройте этот файл и нажмите Run (или ПКМ -> Run 'build_exe').
    3. Готовый файл: dist/NanoMerger/NanoMerger.exe.

Один самодостаточный EXE (медленнее старт, больше размер):
    python build_exe.py --onefile

Скрипт по умолчанию создаёт отдельное окружение .venv-build и устанавливает
зависимости сам. ODA File Converter НЕ скачивается и НЕ упаковывается в EXE.
"""

from __future__ import annotations

import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "NanoMerger"
ENTRY = ROOT / "nanomerger" / "desktop_entry.py"
ICON = ROOT / "nanomerger" / "assets" / "icon.ico"
LOGO = ROOT / "nanomerger" / "assets" / "logo.svg"
BUILD_VENV = ROOT / ".venv-build"
MIN_PYTHON = (3, 10)
MAX_PYTHON = (3, 13)  # совместимо с закреплённой веткой PySide6 6.8–6.9


def check_python(version: tuple[int, int] | None = None) -> None:
    version = version or sys.version_info[:2]
    if not MIN_PYTHON <= version <= MAX_PYTHON:
        raise SystemExit(
            f"Нужен Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}–{MAX_PYTHON[0]}.{MAX_PYTHON[1]} "
            f"(рекомендуется 3.11/3.12 x64), сейчас {version[0]}.{version[1]}. "
            "Выберите подходящий интерпретатор в PyCharm: Settings -> Project -> Python Interpreter."
        )


def run(command: list[str | Path], *, cwd: Path = ROOT) -> None:
    args = [str(part) for part in command]
    printable = subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)
    print(f"\n> {printable}", flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def venv_python() -> Path:
    return BUILD_VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_build_python(args: argparse.Namespace) -> Path:
    if args.use_current_env:
        return Path(sys.executable)
    python = venv_python()
    if python.is_file():
        return python
    if args.skip_install:
        raise SystemExit(
            f"Окружение сборки не найдено: {BUILD_VENV}. Запустите без --skip-install "
            "или используйте --use-current-env для интерпретатора PyCharm."
        )
    run([sys.executable, "-m", "venv", str(BUILD_VENV)])
    if not python.is_file():
        raise SystemExit(f"Не удалось создать окружение сборки: {python}")
    return python


def install_dependencies(python: Path, args: argparse.Namespace) -> None:
    if args.skip_install:
        probe = subprocess.run(
            [str(python), "-c", "import PyInstaller, PySide6, ezdxf, matplotlib, nanomerger"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            raise SystemExit(
                "В выбранном окружении не хватает зависимостей сборки.\n"
                f"{probe.stderr.strip()}\n"
                "Запустите скрипт без --skip-install либо выполните: "
                'pip install -e ".[gui,build]"'
            )
        return
    run([python, "-m", "pip", "install", "--upgrade", "pip"])
    run([python, "-m", "pip", "install", "-e", ".[gui,build]"])


def build_command(python: Path, args: argparse.Namespace) -> list[str]:
    if not ENTRY.is_file():
        raise SystemExit(f"Не найдена точка входа: {ENTRY}")
    dist = ROOT / "dist"
    work = ROOT / "build" / "pyinstaller"
    command = [
        str(python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--noupx",
        "--name",
        APP_NAME,
        "--windowed" if not args.console else "--console",
        "--onefile" if args.onefile else "--onedir",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        "--paths",
        str(ROOT),
        "--log-level",
        "INFO",
        # Ленивые импорты ядра и ресурсы пакета должны попасть в сборку.
        "--collect-submodules",
        "nanomerger",
        "--collect-data",
        "nanomerger",
        "--collect-all",
        "ezdxf",
        "--collect-all",
        "matplotlib",
        "--hidden-import",
        "nanomerger.merger",
        "--hidden-import",
        "nanomerger.pdf",
        "--hidden-import",
        "ezdxf.addons.drawing.matplotlib",
        "--hidden-import",
        "matplotlib.backends.backend_pdf",
        "--hidden-import",
        "PySide6.QtSvg",
        "--add-data",
        f"{LOGO}{os.pathsep}nanomerger/assets",
    ]
    if not args.no_clean:
        command.append("--clean")
    if ICON.is_file():
        command.extend(["--icon", str(ICON)])
    command.append(str(ENTRY))
    return command


def expected_exe(args: argparse.Namespace) -> Path:
    if args.onefile:
        return ROOT / "dist" / f"{APP_NAME}.exe"
    return ROOT / "dist" / APP_NAME / f"{APP_NAME}.exe"


def write_distribution_notes(exe: Path, args: argparse.Namespace) -> None:
    notes = (
        "NanoMerger — запуск и важные условия\n"
        "===================================\n\n"
        "1. Запустите NanoMerger.exe.\n"
        "2. Установите отдельно ODA File Converter и укажите путь к ODAFileConverter.exe.\n"
        "   Без ODA невозможно читать и записывать настоящие DWG.\n"
        "3. Выберите папку с нумерованными DWG, папку результата и нажмите «Объединить DWG + PDF».\n\n"
        "PDF является векторной визуализацией геометрии, не native-печатью CAD с CTB/STB.\n"
        "Исходный Paper Space, XREF, proxy и ряд специальных объектов не поддерживаются первой версией.\n"
        "Перед выдачей заказчику проверьте комплект по docs/ACCEPTANCE.md в репозитории.\n\n"
        "Исходный код: https://github.com/googlios200008-cloud/NanoCad_Merger\n"
    )
    if args.onefile:
        notes_path = exe.parent / f"{APP_NAME}_START_HERE.txt"
        notices_path = exe.parent / f"{APP_NAME}_THIRD_PARTY_NOTICES.md"
    else:
        notes_path = exe.parent / "START_HERE.txt"
        notices_path = exe.parent / "THIRD_PARTY_NOTICES.md"
        license_src = ROOT / "LICENSE"
        if license_src.is_file():
            shutil.copy2(license_src, exe.parent / "LICENSE")
    notes_path.write_text(notes, encoding="utf-8")
    notices_src = ROOT / "THIRD_PARTY_NOTICES.md"
    if notices_src.is_file():
        shutil.copy2(notices_src, notices_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Собрать NanoMerger.exe на Windows (PyCharm: просто Run этого файла).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="один EXE вместо папки dist/NanoMerger; старт медленнее",
    )
    parser.add_argument(
        "--use-current-env",
        action="store_true",
        help="собирать текущим интерпретатором PyCharm, не создавать .venv-build",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="не устанавливать зависимости, только проверить и собрать",
    )
    parser.add_argument(
        "--console", action="store_true", help="EXE с консолью для диагностики ошибок запуска"
    )
    parser.add_argument(
        "--no-clean", action="store_true", help="не очищать кэш PyInstaller перед сборкой"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать команду сборки без установки и запуска PyInstaller",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    check_python()
    if args.dry_run:
        python = Path(sys.executable) if args.use_current_env else venv_python()
        command = build_command(python, args)
        print("Команда сборки (dry run):")
        print(subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command))
        print(f"Ожидаемый результат: {expected_exe(args)}")
        return 0
    if sys.platform != "win32":
        print(
            "Windows EXE нужно собирать на Windows. PyInstaller не является кросс-компилятором.\n"
            "Откройте проект в PyCharm на Windows и запустите build_exe.py.\n"
            "На другой ОС доступен только --dry-run для проверки команды.",
            file=sys.stderr,
        )
        return 2
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        print(
            "Предупреждение: рекомендуется Windows x64; на ARM64 совместимость колёс не гарантирована.",
            file=sys.stderr,
        )
    try:
        python = ensure_build_python(args)
        install_dependencies(python, args)
        run(build_command(python, args))
        exe = expected_exe(args)
        if not exe.is_file() or exe.stat().st_size == 0:
            raise SystemExit(f"PyInstaller завершился, но EXE не найден: {exe}")
        write_distribution_notes(exe, args)
        print("\nСборка завершена успешно.")
        print(f"EXE: {exe}")
        print(f"Размер: {exe.stat().st_size / 1024 / 1024:.1f} MiB")
        print(
            "ODA File Converter установите отдельно. Проверьте EXE на контрольном комплекте EPLAN."
        )
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"\nОшибка команды, код {exc.returncode}. Смотрите вывод выше.", file=sys.stderr)
        return exc.returncode or 1
    except KeyboardInterrupt:
        print("\nСборка прервана пользователем.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
