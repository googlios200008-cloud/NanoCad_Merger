"""Deterministic folder discovery and trailing-number ordering."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .errors import InputError
from .models import InputFormat, SourceFile

TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)$")


def parse_name(path: Path) -> SourceFile:
    stem = path.stem
    match = TRAILING_NUMBER.fullmatch(stem)
    if match:
        prefix = match.group(1).rstrip(" _-.")
        try:
            number = int(match.group(2))
        except ValueError as exc:
            raise InputError(f"Слишком длинный номер в имени файла: {path.name}") from exc
    else:
        prefix, number = stem.rstrip(" _-."), None
    return SourceFile(path=path, prefix=prefix, number=number)


def scan_folder(
    folder: str | Path, input_format: InputFormat = "dwg"
) -> tuple[list[SourceFile], list[str]]:
    """Scan only the selected folder. Numeric suffixes are compared as integers.

    Equal numbers within one prefix (including different zero padding) are an
    error, not an arbitrary filesystem-dependent ordering. Unnumbered names go
    after numbered names of the same prefix and generate a warning.
    """
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise InputError(f"Папка не найдена: {root}")
    extensions = (
        {".dwg"}
        if input_format == "dwg"
        else {".dxf"}
        if input_format == "dxf"
        else {".dwg", ".dxf"}
    )
    try:
        candidates = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in extensions]
    except OSError as exc:
        raise InputError(f"Не удалось прочитать папку {root}: {exc}") from exc
    files = sorted((parse_name(p) for p in candidates), key=lambda item: item.sort_key)
    if not files:
        raise InputError(f"В папке нет файлов {', '.join(sorted(extensions))}: {root}")

    warnings: list[str] = []
    groups: dict[tuple[str, int], list[str]] = defaultdict(list)
    seen_paths: dict[Path, str] = {}
    for item in files:
        resolved = item.path.resolve()
        if resolved in seen_paths:
            raise InputError(
                f"Один и тот же файл указан дважды: {seen_paths[resolved]} / {item.name}"
            )
        seen_paths[resolved] = item.name
        if item.number is None:
            warnings.append(
                f"В имени «{item.name}» нет конечного номера; файл помещён после нумерованных файлов своей группы."
            )
        else:
            groups[(item.prefix.casefold(), item.number)].append(item.name)
    duplicates = [names for names in groups.values() if len(names) > 1]
    if duplicates:
        pairs = "; ".join(" / ".join(names) for names in duplicates)
        raise InputError(
            f"Неоднозначный порядок: одинаковые номера у файлов {pairs}. Исправьте имена перед объединением."
        )
    prefixes = {item.prefix.casefold() for item in files}
    if len(prefixes) > 1:
        warnings.append(
            "Обнаружены разные префиксы имён. Сначала сортировка по префиксу, затем по конечному номеру."
        )
    for prefix in prefixes:
        numbers = sorted(
            item.number
            for item in files
            if item.prefix.casefold() == prefix and item.number is not None
        )
        missing = sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers)) if numbers else []
        if missing:
            shown = ", ".join(map(str, missing[:20])) + ("…" if len(missing) > 20 else "")
            warnings.append(
                f"В последовательности «{prefix or '(без префикса)'}» пропущены номера: {shown}."
            )
    return files, warnings
