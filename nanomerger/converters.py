"""DWG/DXF adapters. The production DWG adapter invokes the real ODA executable.

No DXF bytes are ever renamed to ``.dwg``. Converters work on isolated staging
directories, enforce a timeout, and support cooperative process cancellation.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .errors import CancelledError, ConversionError, DependencyError, InputError
from .models import DWG_VERSIONS, CancelEvent


def check_cancel(cancel: CancelEvent | None) -> None:
    if cancel is not None and cancel.is_set():
        raise CancelledError("Объединение отменено пользователем.")


class DrawingConverter(Protocol):
    def read_drawings(
        self, sources: Sequence[Path], destination: Path, *, cancel: CancelEvent | None = None
    ) -> dict[Path, Path]:
        """Return a DXF path for every original source path."""
        ...

    def write_dwg(
        self, dxf_path: Path, dwg_path: Path, version: str, *, cancel: CancelEvent | None = None
    ) -> None: ...


def find_oda(executable: str | Path | None = None) -> Path | None:
    explicit = executable or os.environ.get("NANOMERGER_ODA")
    if explicit:
        path = Path(explicit).expanduser()
        return path.resolve() if path.is_file() else None
    found = shutil.which("ODAFileConverter")
    if found:
        return Path(found).resolve()
    candidates: list[Path] = []
    if sys.platform == "win32":
        for base in (
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        ):
            if base:
                candidates.extend(Path(base).glob("ODA/ODAFileConverter*/ODAFileConverter.exe"))
                candidates.extend(Path(base).glob("ODA/ODAFileConverter*/*/ODAFileConverter.exe"))
    elif sys.platform == "darwin":
        candidates = [Path("/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter")]
    else:
        candidates = [
            Path("/usr/bin/ODAFileConverter"),
            Path("/usr/local/bin/ODAFileConverter"),
            Path.home() / "Applications" / "ODAFileConverter.AppImage",
        ]
    return next((p.resolve() for p in sorted(candidates, reverse=True) if p.is_file()), None)


def _stop_process(process: subprocess.Popen, *, cancelled: bool) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        elif sys.platform == "win32":
            # ODA may start helper processes; terminate the tree on cancel/timeout.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        else:
            process.terminate()
    except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (ProcessLookupError, OSError):
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


class OdaConverter:
    """Batch ODA File Converter adapter.

    ODA is a separately installed, proprietary application. Its license must be
    accepted by the user; it is not downloaded or bundled by NanoMerger.
    """

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        timeout_seconds: float = 1800.0,
        audit: bool = True,
    ) -> None:
        self.executable = find_oda(executable)
        self.timeout_seconds = timeout_seconds
        self.audit = audit

    def _run(self, arguments: list[str], *, cancel: CancelEvent | None) -> str:
        check_cancel(cancel)
        if self.executable is None:
            raise DependencyError(
                "Не найден ODA File Converter. Установите его и укажите путь к ODAFileConverter "
                "в настройках, параметре --oda или переменной NANOMERGER_ODA."
            )
        env = os.environ.copy()
        if sys.platform.startswith("linux"):
            # Only the child converter is headless; never change the host Engi GUI.
            env.setdefault("QT_QPA_PLATFORM", "offscreen")
        command = [str(self.executable), *arguments]
        kwargs: dict = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        elif sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            with tempfile.TemporaryFile(mode="w+") as output:
                process = subprocess.Popen(
                    command, stdout=output, stderr=subprocess.STDOUT, env=env, **kwargs
                )
                deadline = time.monotonic() + self.timeout_seconds
                cancelled = False
                while process.poll() is None:
                    if cancel is not None and cancel.is_set():
                        cancelled = True
                        break
                    if time.monotonic() >= deadline:
                        break
                    try:
                        process.wait(timeout=0.2)
                    except subprocess.TimeoutExpired:
                        pass
                if process.poll() is None:
                    _stop_process(process, cancelled=cancelled)
                    if cancelled:
                        raise CancelledError("Конвертация ODA отменена.")
                    raise ConversionError(
                        f"ODA не завершил конвертацию за {self.timeout_seconds:g} с."
                    )
                output.seek(0)
                log = output.read()[-8000:]
        except OSError as exc:
            raise ConversionError(f"Не удалось запустить ODA: {exc}") from exc
        if process.returncode != 0:
            raise ConversionError(f"ODA завершился с кодом {process.returncode}.", details=log)
        return log

    @staticmethod
    def _stage(sources: Sequence[Path], folder: Path) -> dict[Path, Path]:
        folder.mkdir(parents=True, exist_ok=True)
        mapping: dict[Path, Path] = {}
        names: set[str] = set()
        for source in sources:
            source = Path(source).resolve()
            if not source.is_file():
                raise InputError(f"Исходный файл исчез или недоступен: {source}")
            # ODA's extension filter is case-sensitive on some platforms.
            staged_name = f"{source.stem}{source.suffix.lower()}"
            if staged_name.casefold() in names:
                raise InputError(f"Неоднозначные имена для ODA: {source.name}. Переименуйте файлы.")
            names.add(staged_name.casefold())
            staged = folder / staged_name
            shutil.copy2(source, staged)
            mapping[source] = staged
        return mapping

    def read_drawings(
        self, sources: Sequence[Path], destination: Path, *, cancel: CancelEvent | None = None
    ) -> dict[Path, Path]:
        if not sources:
            return {}
        destination = Path(destination).resolve()
        with tempfile.TemporaryDirectory(prefix="nanomerger-oda-in-") as tmp:
            staged = self._stage(sources, Path(tmp) / "input")
            destination.mkdir(parents=True, exist_ok=True)
            # The staging directory contains only explicitly selected files.
            # A wildcard also handles both DWG and DXF in auto-input mode.
            log = self._run(
                [
                    str(staged[next(iter(staged))].parent),
                    str(destination),
                    "ACAD2018",
                    "DXF",
                    "0",
                    "1" if self.audit else "0",
                    "*",
                ],
                cancel=cancel,
            )
            result: dict[Path, Path] = {}
            missing: list[str] = []
            for original, infile in staged.items():
                converted = destination / infile.with_suffix(".dxf").name
                check_cancel(cancel)
                if not converted.is_file() or converted.stat().st_size == 0:
                    missing.append(original.name)
                else:
                    result[original] = converted
            if missing:
                raise ConversionError("ODA не создал DXF для: " + ", ".join(missing), details=log)
            return result

    def write_dwg(
        self, dxf_path: Path, dwg_path: Path, version: str, *, cancel: CancelEvent | None = None
    ) -> None:
        if version not in DWG_VERSIONS:
            raise InputError(f"Неподдерживаемая версия DWG: {version}")
        dxf_path, dwg_path = Path(dxf_path), Path(dwg_path)
        with tempfile.TemporaryDirectory(prefix="nanomerger-oda-out-") as tmp:
            root = Path(tmp)
            infile = root / "input" / dxf_path.name
            self._stage([dxf_path], infile.parent)
            outfile = root / "output"
            outfile.mkdir()
            log = self._run(
                [
                    str(infile.parent),
                    str(outfile),
                    DWG_VERSIONS[version],
                    "DWG",
                    "0",
                    "1" if self.audit else "0",
                    "*.dxf",
                ],
                cancel=cancel,
            )
            converted = outfile / infile.with_suffix(".dwg").name
            if not converted.is_file():
                raise ConversionError("ODA не создал итоговый DWG.", details=log)
            with converted.open("rb") as stream:
                signature = stream.read(6)
            if not signature.startswith(b"AC10"):
                raise ConversionError(
                    "Конвертер вернул не DWG; результат не опубликован.", details=log
                )
            check_cancel(cancel)
            dwg_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(converted, dwg_path)


class DxfPassthroughConverter:
    """Explicit DXF-only development/demo adapter. It cannot produce DWG."""

    def read_drawings(
        self, sources: Sequence[Path], destination: Path, *, cancel: CancelEvent | None = None
    ) -> dict[Path, Path]:
        result = {}
        for source in sources:
            check_cancel(cancel)
            source = Path(source).resolve()
            if source.suffix.lower() != ".dxf":
                raise InputError("DXF-адаптер не читает DWG. Укажите ODA File Converter.")
            if not source.is_file():
                raise InputError(f"Файл не найден: {source}")
            result[source] = source
        return result

    def write_dwg(
        self, dxf_path: Path, dwg_path: Path, version: str, *, cancel: CancelEvent | None = None
    ) -> None:
        raise DependencyError(
            "Для записи настоящего DWG нужен ODA File Converter. DXF не переименовывается в DWG."
        )
