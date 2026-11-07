"""Typed, GUI-independent job configuration and results."""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .errors import InputError

InputFormat = Literal["dwg", "dxf", "auto"]
OutputFormat = Literal["dwg", "dxf"]
ProgressCallback = Callable[["Progress"], None]
CancelEvent = threading.Event
PAPERS = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "A0": (841.0, 1189.0),
}
DWG_VERSIONS = {
    "R2000": "ACAD2000",
    "R2004": "ACAD2004",
    "R2007": "ACAD2007",
    "R2010": "ACAD2010",
    "R2013": "ACAD2013",
    "R2018": "ACAD2018",
}


def safe_stem(value: str, fallback: str = "merged") -> str:
    """Make a portable single-component filename without silently accepting paths."""
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    value = re.sub(r"\s+", " ", value)[:120].strip(" .") or fallback
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])", value):
        value = f"_{value}"
    return value


@dataclass(frozen=True)
class MergeOptions:
    input_format: InputFormat = "dwg"
    output_format: OutputFormat = "dwg"
    dwg_version: str = "R2018"
    gap_mm: float = 50.0
    columns: int = 0
    margin_mm: float = 10.0
    paper: str = "auto"
    color_pdf: bool = False
    overwrite: bool = False
    timeout_seconds: float = 1800.0

    def __post_init__(self) -> None:
        if self.input_format not in ("dwg", "dxf", "auto"):
            raise InputError("Формат входа должен быть dwg, dxf или auto.")
        if self.output_format not in ("dwg", "dxf"):
            raise InputError("Формат результата должен быть dwg или dxf.")
        if self.dwg_version not in DWG_VERSIONS:
            raise InputError(f"Неизвестная версия DWG: {self.dwg_version}")
        for name in ("gap_mm", "margin_mm", "timeout_seconds"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise InputError(f"Параметр {name} должен быть конечным числом.")
        if not 0 <= self.gap_mm <= 100_000:
            raise InputError("Зазор между чертежами должен быть от 0 до 100000 мм.")
        if not 0 <= self.margin_mm <= 100:
            raise InputError("Поля листа должны быть от 0 до 100 мм.")
        if isinstance(self.columns, bool) or not isinstance(self.columns, int) or self.columns < 0:
            raise InputError(
                "Число столбцов должно быть целым: 0 = одна горизонтальная лента, 1+ = сетка."
            )
        if self.timeout_seconds <= 0:
            raise InputError("Таймаут конвертера должен быть больше нуля.")
        if self.paper not in ("auto", "source", *PAPERS):
            raise InputError("Формат листа: auto, source или A4–A0.")
        if self.output_format == "dxf" and self.input_format == "dwg":
            raise InputError(
                "Для входа DWG используйте конвертер ODA и результат DWG; режим DXF предназначен для DXF-входа."
            )


@dataclass(frozen=True)
class SourceFile:
    path: Path
    prefix: str
    number: int | None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def sort_key(self) -> tuple:
        return (
            self.prefix.casefold(),
            self.number is None,
            self.number if self.number is not None else 0,
            self.name.casefold(),
            self.name,
        )


@dataclass(frozen=True)
class Progress:
    stage: str
    completed: int
    total: int
    message: str

    @property
    def fraction(self) -> float:
        return min(1.0, max(0.0, self.completed / self.total)) if self.total else 0.0


@dataclass(frozen=True)
class SheetInfo:
    index: int
    source_name: str
    file_number: int | None
    layout_name: str
    block_name: str
    source_units: int
    unit_scale: float
    source_bounds_mm: tuple[float, float, float, float]
    model_bounds_mm: tuple[float, float, float, float]
    paper_mm: tuple[float, float]
    paper_source: str
    viewport_scale: float


@dataclass(frozen=True)
class MergeResult:
    output_dir: Path
    cad_path: Path
    pdf_path: Path
    report_path: Path
    dwg_path: Path | None
    dxf_path: Path | None
    sheets: tuple[SheetInfo, ...]
    warnings: tuple[str, ...] = ()
    duration_seconds: float = 0.0
    pdf_engine: str = "ezdxf + matplotlib (vector preview; not a CAD plot)"
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        from dataclasses import asdict

        data = asdict(self)
        for key in ("output_dir", "cad_path", "pdf_path", "report_path", "dwg_path", "dxf_path"):
            if data[key] is not None:
                data[key] = str(data[key])
        return data
