"""Preflight and transactional publication of a complete result set."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .errors import ConversionError, InputError, OutputExistsError
from .models import MergeOptions, SourceFile, safe_stem


def default_output_name(folder: Path, sources: Sequence[SourceFile]) -> str:
    prefixes = {item.prefix for item in sources}
    base = next(iter(prefixes)) if len(prefixes) == 1 and next(iter(prefixes)) else folder.name
    return safe_stem(f"{base}_merged")


def output_paths(
    folder: Path,
    output_dir: Path | None,
    output_name: str | None,
    sources: Sequence[SourceFile],
    options: MergeOptions,
) -> dict[str, Path]:
    destination = Path(output_dir).expanduser().resolve() if output_dir else folder / "result"
    name = output_name or default_output_name(folder, sources)
    if Path(name).name != name or "\\" in name or "/" in name:
        raise InputError("Имя результата должно быть именем файла без папок и разделителей.")
    if name.lower().endswith((".dwg", ".dxf", ".pdf")):
        name = Path(name).stem
    stem = safe_stem(name)
    cad = destination / f"{stem}.{options.output_format}"
    paths = {
        "cad": cad,
        "pdf": destination / f"{stem}.pdf",
        "report": destination / f"{stem}.report.json",
    }
    originals = {item.path.resolve() for item in sources}
    for path in paths.values():
        if path.resolve() in originals:
            raise InputError(
                f"Результат совпадает с исходным файлом: {path}. Выберите другое имя или папку."
            )
    return paths


def check_existing(paths: dict[str, Path], overwrite: bool) -> None:
    if overwrite:
        return
    existing = [str(path) for path in paths.values() if path.exists()]
    if existing:
        raise OutputExistsError(
            "Файлы результата уже существуют: "
            + "; ".join(existing)
            + ". Выберите другое имя или включите перезапись."
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish(staged: dict[Path, Path], *, overwrite: bool) -> None:
    """Publish only after CAD, PDF and report are complete.

    Files are staged on the destination filesystem. Existing outputs are moved
    to backups and restored if any replacement fails. A filesystem cannot make a
    multi-file replacement atomic as a group, so readers should use the report
    as the completion marker; ordinary conversion failures never touch outputs.
    """
    finals = [Path(p).resolve() for p in staged]
    check_existing({str(p): p for p in finals}, overwrite)
    parent = finals[0].parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".nanomerger-backup-", dir=parent) as tmp:
        backup_dir = Path(tmp)
        backups: dict[Path, Path] = {}
        published: list[Path] = []
        try:
            for index, final in enumerate(finals):
                if final.exists():
                    backup = backup_dir / f"{index}_{final.name}"
                    os.replace(final, backup)
                    backups[final] = backup
            for final in finals:
                source = Path(staged[final]) if final in staged else None
                # Resolve callers may supply absolute paths already; use the
                # original mapping without changing its filenames.
                if source is None:
                    source = next(
                        value for key, value in staged.items() if Path(key).resolve() == final
                    )
                os.replace(source, final)
                published.append(final)
        except OSError as exc:
            for final in reversed(published):
                final.unlink(missing_ok=True)
            for final, backup in backups.items():
                if backup.exists():
                    os.replace(backup, final)
            raise ConversionError(
                f"Не удалось записать результат (закройте файлы в CAD и проверьте права): {exc}"
            ) from exc
